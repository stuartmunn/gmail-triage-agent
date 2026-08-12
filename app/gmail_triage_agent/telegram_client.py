"""Outbound Telegram notifications for the triage agent (Phase 1).

Phase 1 trust boundary (see ``CLAUDE.md``): Telegram is **send-only, to one
fixed chat**. The chat ID comes exclusively from the ``TELEGRAM_CHAT_ID`` env
var — never from the model, the message text, or any other input — so the
agent can't be steered into messaging an arbitrary chat. This module only
ever calls ``sendMessage``; it never reads updates or messages.

Credentials are supplied at runtime as env vars and never committed:

- ``TELEGRAM_BOT_TOKEN`` — the BotFather token.
- ``TELEGRAM_CHAT_ID``  — the single destination chat.

Implemented with the standard library only (no extra deps); the blocking
HTTP call is expected to run in a worker thread (see ``agent.py``). The bot
token is never logged or surfaced in error messages.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
CHAT_ENV = "TELEGRAM_CHAT_ID"

# Telegram hard-caps a message at 4096 chars; truncate defensively.
_MAX_MESSAGE_LEN = 4096
_TIMEOUT_SECONDS = 15


class TelegramConfigError(RuntimeError):
    """Raised when Telegram env vars are missing or the message is empty."""


class TelegramSendError(RuntimeError):
    """Raised when the Telegram API rejects or fails the send."""


def _endpoint(token: str) -> str:
    return f"https://api.telegram.org/bot{token}/sendMessage"


def send_message(text: str) -> dict[str, object]:
    """Send ``text`` to the fixed Telegram chat and return a small summary.

    The destination chat ID is read from ``TELEGRAM_CHAT_ID`` only — the
    caller cannot supply or influence it. Raises ``TelegramConfigError`` if
    configuration/input is invalid, or ``TelegramSendError`` if the API call
    fails. Neither exception includes the bot token.
    """
    token = os.environ.get(TOKEN_ENV)
    chat_id = os.environ.get(CHAT_ENV)
    if not token:
        raise TelegramConfigError(
            f"{TOKEN_ENV} is not set (see README → Telegram)."
        )
    if not chat_id:
        raise TelegramConfigError(
            f"{CHAT_ENV} is not set (see README → Telegram)."
        )

    if not isinstance(text, str) or not text.strip():
        raise TelegramConfigError("message must be a non-empty string.")
    text = text[:_MAX_MESSAGE_LEN]

    # Chat ID comes from the environment, never from `text` or any argument.
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    request = urllib.request.Request(
        _endpoint(token),
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        # Telegram returns a JSON body with a "description"; surface that but
        # never the request URL (which embeds the token).
        detail = _describe_http_error(exc)
        raise TelegramSendError(
            f"Telegram API returned HTTP {exc.code}: {detail}"
        ) from None
    except urllib.error.URLError as exc:
        raise TelegramSendError(
            f"Could not reach Telegram API: {exc.reason}"
        ) from None

    if not body.get("ok"):
        raise TelegramSendError(
            f"Telegram API rejected the message: {body.get('description', body)}"
        )
    return {"ok": True, "chat_id": chat_id}


def _describe_http_error(exc: urllib.error.HTTPError) -> str:
    """Extract Telegram's error description without leaking the token/URL."""
    try:
        return str(json.loads(exc.read().decode()).get("description", exc.reason))
    except (ValueError, OSError):
        return str(exc.reason)
