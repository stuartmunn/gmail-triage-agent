"""Bare-bones agent skeleton for the Gmail Triage Agent (GTA-4).

Phase 1 skeleton only — see CLAUDE.md for scope and trust boundaries.

Registers exactly two tools and nothing else:

- ``gmail_search`` (read) — real, read-only Gmail search via the Gmail API
  (``gmail.readonly`` scope only; see ``gmail_client``). No write access of
  any kind.
- ``telegram_notify`` (send) — will eventually notify a single fixed
  Telegram chat ID read from ``TELEGRAM_CHAT_ID``. Stubbed: prints instead
  of calling the Telegram API.

``allowed_tools`` is restricted to just these two — no built-in Claude Code
tools (bash, file read/write, web search, etc.) and no other MCP tools are
registered or permitted. Real Gmail/Telegram credentials and triage logic
are out of scope for this story.
"""

import asyncio
import json
import os
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    create_sdk_mcp_server,
    query,
    tool,
)

from gmail_triage_agent.gmail_client import GmailConfigError, search_messages

MCP_SERVER_NAME = "gmail_triage"


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
        return {
            "content": [{"type": "text", "text": f"gmail_search failed: {exc}"}],
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
    "Send a notification to the configured Telegram chat (stub).",
    {"message": str},
)
async def telegram_notify(args: dict[str, Any]) -> dict[str, Any]:
    """Stub — no real Telegram API call. Chat ID is read from env, never
    supplied by the model, so a future real implementation can't be steered
    into notifying an arbitrary chat."""
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "<unset>")
    message = args.get("message", "")
    print(f"[stub telegram_notify] to chat_id={chat_id}: {message}")
    return {
        "content": [
            {"type": "text", "text": f"[stub] notified chat {chat_id}: {message}"}
        ]
    }


async def main() -> None:
    gmail_triage_server = create_sdk_mcp_server(
        name=MCP_SERVER_NAME,
        version="0.1.0",
        tools=[gmail_search, telegram_notify],
    )

    two_tools = [
        f"mcp__{MCP_SERVER_NAME}__gmail_search",
        f"mcp__{MCP_SERVER_NAME}__telegram_notify",
    ]

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
        system_prompt=(
            "You are the Gmail Triage Agent (Phase 1 skeleton). You have "
            "exactly two tools: gmail_search (read-only) and telegram_notify "
            "(sends to one fixed chat). You have no other tools and no "
            "write access to Gmail."
        ),
    )

    placeholder_prompt = (
        "This is a placeholder run of the Phase 1 skeleton. Briefly confirm "
        "which tools you have available and that you will not use any "
        "others."
    )

    async for message in query(prompt=placeholder_prompt, options=options):
        print(message)


if __name__ == "__main__":
    asyncio.run(main())
