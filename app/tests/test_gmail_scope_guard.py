"""Tests for the read-only Gmail trust-boundary guard.

These lock in the Phase 1 boundary: a token recording any scope beyond
``gmail.readonly`` must be rejected. They also guard against the subtle
google-auth gotcha that ``Credentials.scopes`` reflects the scopes *passed
in*, not those granted — so the guard reads the token's own ``scopes`` field.
"""

import pytest

from gmail_triage_agent.gmail_client import (
    SCOPES,
    GmailConfigError,
    _assert_readonly_scopes,
    _summarise,
)

READONLY = "https://www.googleapis.com/auth/gmail.readonly"
MODIFY = "https://www.googleapis.com/auth/gmail.modify"
SEND = "https://www.googleapis.com/auth/gmail.send"


def test_readonly_token_passes():
    # Exactly the allowed scope — no exception.
    _assert_readonly_scopes({"scopes": list(SCOPES)})


def test_modify_scope_rejected():
    with pytest.raises(GmailConfigError, match="beyond read-only"):
        _assert_readonly_scopes({"scopes": [READONLY, MODIFY]})


def test_send_only_scope_rejected():
    with pytest.raises(GmailConfigError, match="beyond read-only"):
        _assert_readonly_scopes({"scopes": [SEND]})


def test_missing_scopes_rejected():
    with pytest.raises(GmailConfigError, match="no scopes recorded"):
        _assert_readonly_scopes({})


def test_empty_scopes_rejected():
    with pytest.raises(GmailConfigError, match="no scopes recorded"):
        _assert_readonly_scopes({"scopes": []})


def test_summarise_extracts_headers_case_insensitively():
    msg = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "hello",
        "payload": {
            "headers": [
                {"name": "from", "value": "a@example.com"},
                {"name": "Subject", "value": "Hi"},
                {"name": "DATE", "value": "Mon, 1 Jan 2026"},
            ]
        },
    }
    assert _summarise(msg) == {
        "id": "m1",
        "thread_id": "t1",
        "from": "a@example.com",
        "subject": "Hi",
        "date": "Mon, 1 Jan 2026",
        "snippet": "hello",
    }
