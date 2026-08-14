"""Cost accounting for triage runs (GTA-12).

Every triage API call returns its input/output token counts (captured on
``model_router.TriageResult.usage`` since GTA-11). This module turns those raw
counts into money: it prices each call, rolls the per-call costs up per email
and per run, and writes the figures somewhere queryable so GTA-11's escalation
threshold can be tuned against what a run actually costs.

Design notes / trust boundary (see ``CLAUDE.md``):

- **Pricing is config, never hardcoded rates baked into logic.** Models get
  repriced (Sonnet 5's introductory input/output rate of $2/$10 reverts to
  $3/$15 on 2026-08-31), so ``data/pricing.json`` — host-editable, read fresh
  each run like ``known-senders.md`` — overrides the dated in-code defaults
  below. A missing or malformed file degrades to defaults, never fails a run.
- **No email content in the logs.** Cost records carry sender + subject + cost
  + token counts only — never the snippet/body (same rule the escalation log
  follows in ``model_router``).
- **Cost accounting must never fail a triage run.** It is observability layered
  on top of the pipeline, so every I/O path here warns and continues rather
  than raising.

Escalated emails get a per-model breakdown (Haiku pass + Sonnet pass), not just
a combined total, so the escalation's marginal cost is visible.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from gmail_triage_agent import model_router, triage

log = logging.getLogger("gmail_triage.cost")

# Host-editable pricing override, read fresh each run from the data dir.
PRICING_FILENAME = "pricing.json"

# Tokens are priced per million (the unit model pricing is quoted in).
_MTOK = 1_000_000


@dataclass(frozen=True)
class ModelPrice:
    """USD price per 1,000,000 tokens for one model."""

    input_per_mtok: float
    output_per_mtok: float


# Default USD price per million tokens, as of 2026-08-14. These are a fallback
# only: the host overrides any/all of them via ``data/pricing.json`` when models
# are repriced. Keep them here (dated) so a run costs something sensible out of
# the box, but treat the config file as the source of truth.
_DEFAULT_PRICING: dict[str, ModelPrice] = {
    # Haiku: the cheap first pass.
    model_router.HAIKU_MODEL: ModelPrice(input_per_mtok=1.00, output_per_mtok=5.00),
    # Sonnet: the escalated review. Introductory rate (reverts to $3/$15 on
    # 2026-08-31 — update data/pricing.json then).
    model_router.SONNET_MODEL: ModelPrice(input_per_mtok=2.00, output_per_mtok=10.00),
}


@dataclass
class ModelCost:
    """Cost of one model's pass over one email."""

    model: str
    input_tokens: int
    output_tokens: int
    usd: float


@dataclass
class EmailCost:
    """Total cost of triaging one email, broken down by model."""

    sender: str
    subject: str
    escalated: bool
    by_model: list[ModelCost]
    total_usd: float


def load_pricing() -> dict[str, ModelPrice]:
    """Return model pricing, host overrides merged over the in-code defaults.

    Reads ``data/pricing.json`` fresh (no caching) so a reprice takes effect on
    the next run with no rebuild. A missing file yields the defaults; an
    unreadable or malformed file (or a bad individual entry) warns and falls
    back, so pricing problems never fail a triage run.

    Expected shape::

        {"claude-haiku-4-5": {"input_per_mtok": 1.0, "output_per_mtok": 5.0}}
    """
    pricing = dict(_DEFAULT_PRICING)
    path = triage.data_dir() / PRICING_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return pricing
    except OSError as exc:
        log.warning("Could not read %s (%s); using default pricing.", path, exc)
        return pricing

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("%s is not valid JSON (%s); using default pricing.", path, exc)
        return pricing
    if not isinstance(data, dict):
        log.warning("%s is not a JSON object; using default pricing.", path)
        return pricing

    for model, entry in data.items():
        try:
            pricing[model] = ModelPrice(
                input_per_mtok=float(entry["input_per_mtok"]),
                output_per_mtok=float(entry["output_per_mtok"]),
            )
        except (TypeError, KeyError, ValueError) as exc:
            log.warning(
                "Ignoring malformed pricing entry for %r in %s (%s).",
                model,
                path,
                exc,
            )
    return pricing


def _coerce_tokens(value: Any) -> int:
    """Token counts come off the API response and can be missing/None."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def cost_for_result(result: model_router.TriageResult, pricing: dict[str, ModelPrice]) -> ModelCost:
    """Price one model pass from its captured token usage."""
    usage = result.usage or {}
    input_tokens = _coerce_tokens(usage.get("input_tokens"))
    output_tokens = _coerce_tokens(usage.get("output_tokens"))

    price = pricing.get(result.model)
    if price is None:
        log.warning(
            "No pricing for model %r; counting its cost as $0 (add it to %s).",
            result.model,
            PRICING_FILENAME,
        )
        usd = 0.0
    else:
        usd = (
            input_tokens / _MTOK * price.input_per_mtok
            + output_tokens / _MTOK * price.output_per_mtok
        )
    return ModelCost(result.model, input_tokens, output_tokens, usd)


def email_cost(verdict: model_router.MessageVerdict, pricing: dict[str, ModelPrice]) -> EmailCost:
    """Total the cost of every model pass on one email, keeping the breakdown."""
    by_model = [cost_for_result(r, pricing) for r in verdict.results]
    total = sum(m.usd for m in by_model)
    return EmailCost(
        sender=verdict.sender,
        subject=verdict.subject,
        escalated=verdict.escalated,
        by_model=by_model,
        total_usd=total,
    )


def record_run(verdicts: list[model_router.MessageVerdict]) -> None:
    """Price a completed triage run: log a running total and append records.

    Called from the pipeline (``agent.py``) once triage produces its verdicts.
    Never raises — cost accounting is observability, not correctness, so it
    warns and returns rather than failing the run.
    """
    if not verdicts:
        return

    pricing = load_pricing()
    costs = [email_cost(v, pricing) for v in verdicts]

    # Log the run total first, so the operator sees it on stdout / in triage.log
    # even if the file writes below fail.
    _log_summary(costs)
    _append_records(costs)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_totals(costs: list[EmailCost]) -> tuple[float, dict[str, float], int]:
    """Roll per-email costs up into a run total, per-model totals, escalations."""
    total = 0.0
    per_model: dict[str, float] = {}
    escalated = 0
    for cost in costs:
        total += cost.total_usd
        if cost.escalated:
            escalated += 1
        for m in cost.by_model:
            per_model[m.model] = per_model.get(m.model, 0.0) + m.usd
    return total, per_model, escalated


def _log_summary(costs: list[EmailCost]) -> None:
    """Emit the run's running total as a single easy-to-check INFO line."""
    total, per_model, escalated = _run_totals(costs)
    breakdown = ", ".join(
        f"{model}=${usd:.4f}" for model, usd in sorted(per_model.items())
    )
    log.info(
        "Run cost: $%.4f across %d email(s), %d escalated%s",
        total,
        len(costs),
        escalated,
        f" ({breakdown})" if breakdown else "",
    )


def _append_records(costs: list[EmailCost]) -> None:
    """Append per-email cost lines and a run-summary line; a write failure warns.

    Two JSONL files under ``data/logs/`` (queryable with ``jq``; daily totals
    are derivable by grouping ``cost-summary.jsonl`` on ``ts``):

    - ``costs.jsonl`` — one line per email (sender, subject, cost, tokens; no
      body).
    - ``cost-summary.jsonl`` — one line per run (total + per-model breakdown).
    """
    log_dir = triage.data_dir() / "logs"
    ts = _now_iso()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "costs.jsonl").open("a", encoding="utf-8") as handle:
            for cost in costs:
                handle.write(json.dumps(_email_record(ts, cost), ensure_ascii=False) + "\n")

        total, per_model, escalated = _run_totals(costs)
        summary = {
            "ts": ts,
            "emails": len(costs),
            "escalated": escalated,
            "total_usd": round(total, 6),
            "by_model": {model: round(usd, 6) for model, usd in sorted(per_model.items())},
        }
        with (log_dir / "cost-summary.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, ensure_ascii=False) + "\n")
    except (OSError, ValueError, TypeError) as exc:
        # Never let a logging failure (I/O *or* serialization) fail a run.
        log.warning("Could not write cost records: %s", exc)


def _email_record(ts: str, cost: EmailCost) -> dict[str, Any]:
    """One per-email cost record — sender/subject/cost/tokens only, no body."""
    return {
        "ts": ts,
        "sender": cost.sender,
        "subject": cost.subject,
        "escalated": cost.escalated,
        "total_usd": round(cost.total_usd, 6),
        "by_model": [
            {
                "model": m.model,
                "input_tokens": m.input_tokens,
                "output_tokens": m.output_tokens,
                "usd": round(m.usd, 6),
            }
            for m in cost.by_model
        ],
    }
