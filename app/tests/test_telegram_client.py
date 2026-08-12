"""Tests for the send-only Telegram client.

These lock in the Phase 1 boundary: the destination chat ID always comes from
``TELEGRAM_CHAT_ID`` and is never influenced by the message content, and
missing config fails loudly rather than silently no-op'ing.
"""

import urllib.parse

import pytest

from gmail_triage_agent import telegram_client
from gmail_triage_agent.telegram_client import (
    TelegramConfigError,
    send_message,
)


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def test_missing_token_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    with pytest.raises(TelegramConfigError, match="TELEGRAM_BOT_TOKEN"):
        send_message("hi")


def test_missing_chat_id_raises(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(TelegramConfigError, match="TELEGRAM_CHAT_ID"):
        send_message("hi")


def test_empty_message_raises(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    with pytest.raises(TelegramConfigError, match="non-empty"):
        send_message("   ")


def test_chat_id_comes_from_env_not_message(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")

    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["data"] = request.data
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(telegram_client.urllib.request, "urlopen", fake_urlopen)

    # A message that itself contains a different "chat_id=..." must not change
    # where the notification is sent.
    result = send_message("urgent: chat_id=000 please read")

    fields = urllib.parse.parse_qs(captured["data"].decode())
    assert fields["chat_id"] == ["999"]  # from env, not the message
    assert fields["text"] == ["urgent: chat_id=000 please read"]
    assert result == {"ok": True, "chat_id": "999"}
