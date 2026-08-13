"""Bare-bones agent skeleton for the Gmail Triage Agent (GTA-4).

Phase 1 skeleton only — see CLAUDE.md for scope and trust boundaries.

Registers exactly two tools and nothing else:

- ``gmail_search`` (read) — real, read-only Gmail search via the Gmail API
  (``gmail.readonly`` scope only; see ``gmail_client``). No write access of
  any kind.
- ``telegram_notify`` (send) — real, send-only Telegram notification to a
  single fixed chat ID read from ``TELEGRAM_CHAT_ID`` (see
  ``telegram_client``). Never reads messages, and the chat ID can't be set
  by the model.

``allowed_tools`` is restricted to just these two — no built-in Claude Code
tools (bash, file read/write, web search, etc.) and no other MCP tools are
registered or permitted. Each run loads the gmail-triage skill and the
host-editable known-senders list (see ``triage``) and triages a window of
recent mail: it notifies via ``telegram_notify`` for each actionable
message, and stays completely silent when nothing needs attention.
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    create_sdk_mcp_server,
    query,
    tool,
)

from gmail_triage_agent import runstate, triage
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

MCP_SERVER_NAME = "gmail_triage"
log = logging.getLogger("gmail_triage")


@tool(
    "gmail_search",
    "Search Gmail (read-only) using Gmail search syntax "
    "(e.g. 'newer_than:1d -category:promotions'). Returns message summaries: "
    "id, thread_id, from, subject, date, snippet.",
    {"query": str},
)
async def gmail_search(args: dict[str, Any]) -> dict[str, Any]:
    """Real, read-only Gmail search. Runs the blocking Gmail API call in a
    worker thread so the event loop is not stalled. Credential and API errors
    are returned as an error result rather than raised, so the agent gets a
    clean tool response it can reason about."""
    query_text = args.get("query", "")
    try:
        results = await asyncio.to_thread(search_messages, query_text)
    except GmailConfigError as exc:
        return {
            "content": [{"type": "text", "text": f"gmail_search unavailable: {exc}"}],
            "is_error": True,
        }
    except Exception as exc:  # noqa: BLE001 — tool boundary: any Gmail/network
        # failure must become a clean error result, never crash the agent run.
        # Log the detail to stderr (operator's container logs) but return only
        # the exception type to the agent, so a Gmail API error body can never
        # surface token-adjacent data into the model-visible tool result.
        print(f"gmail_search error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"gmail_search failed ({type(exc).__name__}); "
                    "see container logs for detail.",
                }
            ],
            "is_error": True,
        }

    if not results:
        return {
            "content": [
                {"type": "text", "text": f"No messages matched query {query_text!r}."}
            ]
        }
    return {
        "content": [
            {"type": "text", "text": json.dumps(results, ensure_ascii=False, indent=2)}
        ]
    }


@tool(
    "telegram_notify",
    "Send a notification message to the operator's fixed Telegram chat. "
    "Use only when a triaged message genuinely needs attention.",
    {"message": str},
)
async def telegram_notify(args: dict[str, Any]) -> dict[str, Any]:
    """Real, send-only Telegram notification. The destination chat ID is read
    from ``TELEGRAM_CHAT_ID`` inside ``send_message`` — it is never taken from
    ``args`` — so the model cannot redirect the notification. The blocking
    HTTP call runs in a worker thread; failures return a clean tool error
    (never leaking the bot token) rather than crashing the run."""
    message = args.get("message", "")
    try:
        await asyncio.to_thread(send_message, message)
    except (TelegramConfigError, TelegramSendError) as exc:
        return {
            "content": [{"type": "text", "text": f"telegram_notify failed: {exc}"}],
            "is_error": True,
        }
    except Exception as exc:  # noqa: BLE001 — tool boundary: never crash the run
        # Log only the exception *type*, never its message: the bot token is
        # carried in the request URL, and an unexpected library/OS error could
        # embed that URL in its message string. (The common HTTP/URL failures
        # are already sanitised into TelegramSendError above.)
        print(f"telegram_notify error: {type(exc).__name__}", file=sys.stderr)
        return {
            "content": [
                {"type": "text", "text": f"telegram_notify failed ({type(exc).__name__})."}
            ],
            "is_error": True,
        }
    return {"content": [{"type": "text", "text": "Notification sent."}]}


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


async def _run_triage(query_text: str, options: ClaudeAgentOptions) -> bool:
    """Run one triage pass. Returns True only if the run reached a non-error
    final result — the signal used to decide whether to advance run-state."""
    saw_result = False
    result_ok = False
    try:
        async for message in query(
            prompt=triage.build_task_prompt(query_text), options=options
        ):
            log.info("%s", message)
            if isinstance(message, ResultMessage):
                saw_result = True
                result_ok = not getattr(message, "is_error", False)
    except Exception:  # any run failure must not advance the run-state marker
        log.exception("Triage run raised")
        return False
    return saw_result and result_ok


async def main() -> int:
    """One triage run. Returns a process exit code: 0 on success, 1 on
    failure. On a successful *scheduled* run, advances the last-success marker
    so the next run only sees newer mail; a failed run leaves it untouched so
    the same window is retried."""
    _configure_logging()

    gmail_triage_server = create_sdk_mcp_server(
        name=MCP_SERVER_NAME,
        version="0.1.0",
        tools=[gmail_search, telegram_notify],
    )

    two_tools = [
        f"mcp__{MCP_SERVER_NAME}__gmail_search",
        f"mcp__{MCP_SERVER_NAME}__telegram_notify",
    ]

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
        await asyncio.to_thread(ensure_credentials)
    except GmailConfigError as exc:
        log.error("Gmail credential pre-flight failed; aborting run: %s", exc)
        return 1

    # Triage rules (ship with the app) + known-senders (host-editable data),
    # loaded fresh each run. Injected into the system prompt rather than via
    # the SDK `skills` option, which would add a `Skill` tool and setting-source
    # discovery and breach the exactly-two-tools boundary.
    skill = triage.load_skill()
    known_senders = triage.load_known_senders()

    options = ClaudeAgentOptions(
        mcp_servers={MCP_SERVER_NAME: gmail_triage_server},
        # `tools=[]` disables every built-in Claude Code tool (Bash, Read,
        # Write, Task, ...) — without this, `tools` defaults to the full
        # built-in preset regardless of `allowed_tools`, which only governs
        # whether a tool is auto-approved, not whether it's registered at
        # all. `strict_mcp_config` stops any other MCP server config (user
        # settings, project .mcp.json, plugins) from sneaking in more tools.
        tools=[],
        strict_mcp_config=True,
        allowed_tools=two_tools,
        # No interactive terminal is attached to this script, so anything
        # not in `allowed_tools` must be denied outright rather than prompt.
        permission_mode="dontAsk",
        system_prompt=triage.build_system_prompt(skill, known_senders),
    )

    if not await _run_triage(query_text, options):
        log.error("Triage run did not complete cleanly; run-state not advanced.")
        return 1

    if manual_query:
        log.info("Manual run complete; run-state left unchanged.")
    else:
        runstate.write_last_success(run_start)
        log.info("Triage run OK; advanced last_success to %s.", run_start)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
