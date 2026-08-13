"""Model selection for triage: cheap first, escalate on uncertainty (GTA-11).

Every email is classified first by **Haiku** (`claude-haiku-4-5`) — fast and
cheap. Haiku returns a triage decision *and* a confidence. When that
confidence falls below a configurable threshold, the same email is re-run
through **Sonnet** (`claude-sonnet-5`) for a closer look, and Sonnet's verdict
is taken as final. This keeps cost down while spending the more capable model
only where Haiku was unsure.

Design notes / trust boundary (see ``CLAUDE.md``):

- Classification is a structured Messages-API call with **no tools** — the
  model returns ``{decision, confidence, reason}`` and cannot act. Gmail read
  and Telegram send happen elsewhere (``agent.py``), so the Phase-1 boundary
  is unchanged: read-only Gmail, send-only Telegram to a fixed chat.
- The triage *rules* stay model-agnostic (they live in ``SKILL.md`` and are
  composed by ``triage``); the escalation *logic* lives here, separate.
- Email content (the snippet/body) is fed to the model but **never logged** —
  escalation records carry sender + subject only.

The per-message classifier is injectable (``triage_messages(..., classifier=)``)
so tests can exercise the escalation logic without any network calls.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from gmail_triage_agent import triage

log = logging.getLogger("gmail_triage.router")

# Model IDs. Haiku for the cheap first pass; Sonnet for the escalated review.
HAIKU_MODEL = "claude-haiku-4-5"
SONNET_MODEL = "claude-sonnet-5"

# Confidence threshold: Haiku decisions below this are re-run through Sonnet.
# Read fresh from the environment each run (see ``read_threshold``) so it can
# be tuned without rebuilding the image.
THRESHOLD_ENV = "GTA_CONFIDENCE_THRESHOLD"
DEFAULT_CONFIDENCE_THRESHOLD = 0.7

# Output-token ceilings per model. Haiku does a quick classification; Sonnet
# gets more room for its (default, adaptive) thinking on the escalated look.
_MAX_TOKENS = {HAIKU_MODEL: 512, SONNET_MODEL: 2048}
_DEFAULT_MAX_TOKENS = 1024

# Structured-output schema the model must return. Note: JSON-schema numeric
# bounds (minimum/maximum) aren't supported by structured outputs, so the
# 0.0-1.0 range for ``confidence`` is described in prose and clamped below.
_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["notify", "silent"],
            "description": "'notify' if the email needs attention, else 'silent'.",
        },
        "confidence": {
            "type": "number",
            "description": "Certainty in the decision, 0.0 (very unsure) to 1.0 (certain).",
        },
        "reason": {
            "type": "string",
            "description": "One concise line explaining the decision.",
        },
    },
    "required": ["decision", "confidence", "reason"],
    "additionalProperties": False,
}


class ModelRouterError(RuntimeError):
    """Raised when the model classifier is unusable or returns bad output."""


@dataclass
class TriageResult:
    """One model's verdict on one email."""

    decision: str  # "notify" | "silent"
    confidence: float  # clamped to [0.0, 1.0]
    reason: str
    model: str
    # Raw token counts for this call. Captured now (free from the response) so
    # GTA-12 can cost runs; this story does not price anything.
    usage: Optional[dict[str, Optional[int]]] = None


@dataclass
class MessageVerdict:
    """The final triage verdict for one email, plus how we got there."""

    message_id: str
    sender: str
    subject: str
    decision: str  # final decision
    confidence: float  # final confidence
    reason: str  # final reason
    model: str  # model that produced the final verdict
    escalated: bool
    haiku_confidence: float
    results: list[TriageResult] = field(default_factory=list)


# A classifier takes (model, system_prompt, user_prompt) and returns a result.
Classifier = Callable[[str, str, str], TriageResult]


def read_threshold() -> float:
    """Read the confidence threshold from the environment, fresh each run.

    Falls back to ``DEFAULT_CONFIDENCE_THRESHOLD`` (with a warning) when the
    value is missing, non-numeric, or outside ``[0.0, 1.0]``.
    """
    raw = os.environ.get(THRESHOLD_ENV, "").strip()
    if not raw:
        return DEFAULT_CONFIDENCE_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        log.warning(
            "%s=%r is not a number; using default %.2f",
            THRESHOLD_ENV,
            raw,
            DEFAULT_CONFIDENCE_THRESHOLD,
        )
        return DEFAULT_CONFIDENCE_THRESHOLD
    if not 0.0 <= value <= 1.0:
        log.warning(
            "%s=%r is outside [0.0, 1.0]; using default %.2f",
            THRESHOLD_ENV,
            raw,
            DEFAULT_CONFIDENCE_THRESHOLD,
        )
        return DEFAULT_CONFIDENCE_THRESHOLD
    return value


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def classify(
    client: Any, model: str, system_prompt: str, user_prompt: str
) -> TriageResult:
    """Classify one email with ``model`` via the Anthropic Messages API.

    Returns a structured ``{decision, confidence, reason}`` (no tools). Raises
    ``ModelRouterError`` if the response can't be parsed into a valid verdict.
    """
    response = client.messages.create(
        model=model,
        max_tokens=_MAX_TOKENS.get(model, _DEFAULT_MAX_TOKENS),
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        output_config={"format": {"type": "json_schema", "schema": _DECISION_SCHEMA}},
    )

    text = next(
        (
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ),
        None,
    )
    if not text:
        raise ModelRouterError(f"{model} returned no text block to parse.")

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ModelRouterError(f"{model} returned unparsable JSON: {exc}") from exc

    decision = data.get("decision")
    if decision not in ("notify", "silent"):
        raise ModelRouterError(f"{model} returned an invalid decision: {decision!r}")

    try:
        confidence = _clamp01(float(data.get("confidence", 0.0)))
    except (TypeError, ValueError) as exc:
        raise ModelRouterError(
            f"{model} returned a non-numeric confidence: "
            f"{data.get('confidence')!r} ({exc})"
        ) from exc

    reason = str(data.get("reason", "")).strip()

    usage_obj = getattr(response, "usage", None)
    usage = {
        "input_tokens": getattr(usage_obj, "input_tokens", None),
        "output_tokens": getattr(usage_obj, "output_tokens", None),
    }

    return TriageResult(
        decision=decision,
        confidence=confidence,
        reason=reason,
        model=model,
        usage=usage,
    )


def _build_client() -> Any:
    """Build a real Anthropic client, or raise a clear ``ModelRouterError``."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ModelRouterError(
            "ANTHROPIC_API_KEY is not set — the triage classifier needs it "
            "(see README → Configuration)."
        )
    try:
        import anthropic
    except ImportError as exc:  # dependency missing / broken image
        raise ModelRouterError(
            f"the 'anthropic' package is not importable ({exc})."
        ) from exc
    return anthropic.Anthropic()


def _default_classifier() -> Classifier:
    """A classifier bound to a single real Anthropic client for this run."""
    client = _build_client()

    def _run(model: str, system_prompt: str, user_prompt: str) -> TriageResult:
        return classify(client, model, system_prompt, user_prompt)

    return _run


def triage_messages(
    messages: list[dict[str, str]],
    skill: str,
    known_senders: Optional[str],
    *,
    threshold: float,
    classifier: Optional[Classifier] = None,
) -> list[MessageVerdict]:
    """Triage each email Haiku-first, escalating uncertain ones to Sonnet.

    ``classifier`` is injectable for testing; by default it calls the real
    Messages API. A classifier failure propagates so the caller can fail the
    run (and leave the run-state marker untouched), rather than silently
    dropping an email that might be actionable.
    """
    if classifier is None:
        classifier = _default_classifier()

    system_prompt = triage.build_classification_system_prompt(skill, known_senders)
    verdicts: list[MessageVerdict] = []

    for message in messages:
        user_prompt = triage.build_message_prompt(message)

        haiku = classifier(HAIKU_MODEL, system_prompt, user_prompt)
        results = [haiku]
        escalated = haiku.confidence < threshold
        if escalated:
            final = classifier(SONNET_MODEL, system_prompt, user_prompt)
            results.append(final)
        else:
            final = haiku

        verdict = MessageVerdict(
            message_id=message.get("id", ""),
            sender=message.get("from", ""),
            subject=message.get("subject", ""),
            decision=final.decision,
            confidence=final.confidence,
            reason=final.reason,
            model=final.model,
            escalated=escalated,
            haiku_confidence=haiku.confidence,
            results=results,
        )
        if escalated:
            _log_escalation(verdict, threshold)
        verdicts.append(verdict)

    return verdicts


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log_escalation(verdict: MessageVerdict, threshold: float) -> None:
    """Record an escalation: which email, why, and which model ruled finally.

    Emits an INFO log line and appends a structured record to
    ``data/logs/escalations.jsonl``. Sender + subject only — never the
    snippet/body (see ``CLAUDE.md``: no email content in logs).
    """
    log.info(
        "Escalated to Sonnet: from=%r subject=%r haiku_confidence=%.2f "
        "< threshold=%.2f -> final=%s (%s, confidence=%.2f)",
        verdict.sender,
        verdict.subject,
        verdict.haiku_confidence,
        threshold,
        verdict.decision,
        verdict.model,
        verdict.confidence,
    )
    record = {
        "ts": _now_iso(),
        "sender": verdict.sender,
        "subject": verdict.subject,
        "haiku_confidence": round(verdict.haiku_confidence, 4),
        "threshold": threshold,
        "from_model": HAIKU_MODEL,
        "to_model": verdict.model,
        "final_decision": verdict.decision,
        "final_confidence": round(verdict.confidence, 4),
    }
    _append_escalation_record(record)


def _append_escalation_record(record: dict[str, Any]) -> None:
    """Append one JSONL escalation record; a logging failure never fails a run."""
    log_dir = triage.data_dir() / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "escalations.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.warning("Could not write escalation record: %s", exc)
