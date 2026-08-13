"""Entry point for the Gmail Triage Agent (Phase 1).

Phase 1 scope and trust boundaries — see CLAUDE.md. This run is a synchronous
pipeline, not an agentic tool loop:

1. Decide the window of mail to triage (incremental since last success, or a
   manual ``GTA_SEARCH_QUERY`` override for testing) — see ``runstate``.
2. Fetch that window read-only from Gmail (``gmail.readonly`` scope only; see
   ``gmail_client``). No write access of any kind.
3. Triage each message: Haiku classifies every email with a confidence, and
   uncertain ones escalate to Sonnet (see ``model_router`` — GTA-11). The
   models get **no tools** — they return a decision, they cannot act.
4. Notify via Telegram (send-only, to the single fixed ``TELEGRAM_CHAT_ID``;
   see ``telegram_client``) once per actionable message, and stay completely
   silent when nothing needs attention.

The trust boundary is unchanged from earlier phases: read-only Gmail in, a
Telegram message to one fixed chat out, nothing else touched.
"""

import logging
import os
import sys

from gmail_triage_agent import model_router, runstate, triage
from gmail_triage_agent.gmail_client import (
    GmailConfigError,
    ensure_credentials,
    search_messages,
)
from gmail_triage_agent.telegram_client import (
    TelegramConfigError,
    TelegramSendError,
    send_message,
)

log = logging.getLogger("gmail_triage")


def _configure_logging() -> None:
    """Log to the bind-mounted data dir (retrievable for debugging missed or
    failed runs) and to stdout (so an interactive/cron run shows progress)."""
    log_dir = triage.data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "triage.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def _format_notification(verdict: model_router.MessageVerdict) -> str:
    """A concise Telegram summary: who it's from, the subject, and why."""
    return f"{verdict.sender}\n{verdict.subject}\n{verdict.reason}"


def main() -> int:
    """One triage run. Returns a process exit code: 0 on success, 1 on
    failure. On a successful *scheduled* run, advances the last-success marker
    so the next run only sees newer mail; a failed run leaves it untouched so
    the same window is retried."""
    _configure_logging()

    # Decide the window for this run. A manual GTA_SEARCH_QUERY override (used
    # for testing) is honoured but never touches the scheduled run-state.
    manual_query = os.environ.get("GTA_SEARCH_QUERY", "").strip()
    run_start = runstate.now_epoch()
    if manual_query:
        query_text = manual_query
        log.info("Manual run (GTA_SEARCH_QUERY set); run-state will not advance.")
    else:
        last_success = runstate.read_last_success()
        query_text = runstate.incremental_query(last_success)
        log.info(
            "Scheduled run: last_success=%s, window query=%r",
            last_success,
            query_text,
        )

    # Pre-flight the Gmail credentials so a broken/expired token fails the run
    # *before* it can look like a successful (empty) triage and wrongly advance
    # the marker.
    try:
        ensure_credentials()
    except GmailConfigError as exc:
        log.error("Gmail credential pre-flight failed; aborting run: %s", exc)
        return 1

    try:
        messages = search_messages(query_text)
    except GmailConfigError as exc:
        log.error("Gmail search failed; aborting run: %s", exc)
        return 1
    except Exception:  # noqa: BLE001 — any Gmail/network failure fails the run
        # Full detail to the operator's logs (never model- or user-visible);
        # the run fails so the run-state marker is not advanced.
        log.exception("Gmail search raised; run-state not advanced.")
        return 1

    log.info("Fetched %d message(s) for the window.", len(messages))

    if not messages:
        return _finish(manual_query, run_start, note="no messages")

    # Triage rules (ship with the app) + known-senders (host-editable data),
    # loaded fresh each run.
    try:
        skill = triage.load_skill()
    except triage.TriageConfigError as exc:
        log.error("Could not load the triage skill; aborting run: %s", exc)
        return 1
    known_senders = triage.load_known_senders()

    threshold = model_router.read_threshold()
    log.info(
        "Triaging with confidence threshold %.2f (Haiku first, Sonnet on "
        "uncertainty).",
        threshold,
    )

    try:
        verdicts = model_router.triage_messages(
            messages, skill, known_senders, threshold=threshold
        )
    except model_router.ModelRouterError as exc:
        log.error("Triage aborted (model routing): %s; run-state not advanced.", exc)
        return 1
    except Exception:  # noqa: BLE001 — any classifier failure fails the run
        log.exception("Triage raised; run-state not advanced.")
        return 1

    actionable = [v for v in verdicts if v.decision == "notify"]
    log.info(
        "Triage complete: %d/%d actionable, %d escalated to Sonnet.",
        len(actionable),
        len(verdicts),
        sum(1 for v in verdicts if v.escalated),
    )

    try:
        for verdict in actionable:
            send_message(_format_notification(verdict))
            log.info(
                "Notified: from=%r subject=%r (%s)",
                verdict.sender,
                verdict.subject,
                verdict.model,
            )
    except (TelegramConfigError, TelegramSendError) as exc:
        log.error("Telegram notification failed: %s; run-state not advanced.", exc)
        return 1
    except Exception:  # noqa: BLE001 — never crash; fail the run instead
        log.exception("Telegram notification raised; run-state not advanced.")
        return 1

    return _finish(manual_query, run_start)


def _finish(manual_query: str, run_start: int, note: str = "") -> int:
    """Advance the run-state marker on a successful scheduled run (only)."""
    suffix = f" ({note})" if note else ""
    if manual_query:
        log.info("Manual run complete%s; run-state left unchanged.", suffix)
    else:
        runstate.write_last_success(run_start)
        log.info(
            "Triage run OK%s; advanced last_success to %s.", suffix, run_start
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
