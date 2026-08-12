"""Read-only Gmail access for the triage agent (Phase 1).

Phase 1 trust boundary (see ``CLAUDE.md``): Gmail is **read-only**. This
module requests only the ``gmail.readonly`` scope and, as defence in depth,
refuses to authenticate with any token that carries a broader scope — so a
mis-minted credential can never hand the agent write access.

Credentials are supplied at runtime via the ``GMAIL_TOKEN_JSON`` env var: the
JSON of an authorised OAuth user (including the long-lived ``refresh_token``),
as produced one-time by ``authorize_gmail.py``. Nothing is read from disk and
no secret is ever committed. The short-lived access token is refreshed
in-memory on each run; the refresh token in the env var is what persists.
"""

from __future__ import annotations

import json
import os
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# The single scope this project is allowed in Phase 1. Read-only: list/read
# messages and threads, nothing else. Do not add write scopes here without a
# story that explicitly moves the trust boundary (Phase 3 territory).
SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/gmail.readonly",)

TOKEN_ENV = "GMAIL_TOKEN_JSON"

# Cap how much untrusted model-supplied input we forward to the API.
_MAX_QUERY_LEN = 500
_MAX_RESULTS_CAP = 50
_DEFAULT_MAX_RESULTS = 10


class GmailConfigError(RuntimeError):
    """Raised when Gmail credentials are missing, malformed, or over-scoped."""


def _load_credentials() -> Credentials:
    """Build read-only Gmail credentials from ``GMAIL_TOKEN_JSON``.

    Raises ``GmailConfigError`` with actionable guidance if the env var is
    unset/invalid, if the token lacks a refresh token, or if it was minted
    with any scope beyond ``gmail.readonly``.
    """
    raw = os.environ.get(TOKEN_ENV)
    if not raw:
        raise GmailConfigError(
            f"{TOKEN_ENV} is not set. Run authorize_gmail.py once to mint a "
            "read-only Gmail token, then provide it via this env var (see "
            "README → Gmail credentials)."
        )

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GmailConfigError(
            f"{TOKEN_ENV} is not valid JSON: {exc}. It should be the full "
            "authorized-user JSON emitted by authorize_gmail.py."
        ) from exc

    try:
        creds = Credentials.from_authorized_user_info(info, list(SCOPES))
    except ValueError as exc:
        raise GmailConfigError(
            f"{TOKEN_ENV} is missing required fields ({exc}). Re-run "
            "authorize_gmail.py to regenerate it."
        ) from exc

    # Trust-boundary guard: refuse anything broader than read-only, even if
    # the token happens to carry extra scopes.
    granted = set(creds.scopes or [])
    if not granted:
        # from_authorized_user_info fills scopes from SCOPES when the token
        # JSON omits them; an empty set means neither source had any.
        raise GmailConfigError(
            f"{TOKEN_ENV} has no scopes recorded; cannot confirm it is "
            "read-only. Re-run authorize_gmail.py."
        )
    disallowed = granted - set(SCOPES)
    if disallowed:
        raise GmailConfigError(
            "Refusing to authenticate: token carries scopes beyond "
            f"read-only ({sorted(disallowed)}). Phase 1 is read-only Gmail "
            "only — re-mint the token with authorize_gmail.py."
        )

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise GmailConfigError(
                f"{TOKEN_ENV} is invalid and cannot be refreshed (no usable "
                "refresh token). Re-run authorize_gmail.py."
            )
    return creds


def _build_service() -> Any:
    creds = _load_credentials()
    # cache_discovery=False avoids the noisy file-cache warning and keeps the
    # container filesystem untouched.
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers: list[dict[str, str]], name: str) -> str:
    """Return the value of a message header, case-insensitively, or ''."""
    target = name.lower()
    for h in headers:
        if h.get("name", "").lower() == target:
            return h.get("value", "")
    return ""


def search_messages(
    query: str, max_results: int = _DEFAULT_MAX_RESULTS
) -> list[dict[str, str]]:
    """Search Gmail (read-only) and return lightweight message summaries.

    ``query`` is Gmail search syntax (e.g. ``newer_than:1d -category:promotions``).
    It is model-supplied and therefore untrusted: it is only ever passed to
    the Gmail API's ``q`` parameter (never a shell/path), and is length-capped
    here. ``max_results`` is clamped to a sane range.

    Returns a list of dicts with ``id``, ``thread_id``, ``from``, ``subject``,
    ``date``, and ``snippet``. Raises ``GmailConfigError`` on credential
    problems.
    """
    if not isinstance(query, str):
        raise GmailConfigError("query must be a string.")
    query = query.strip()[:_MAX_QUERY_LEN]

    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        max_results = _DEFAULT_MAX_RESULTS
    max_results = max(1, min(max_results, _MAX_RESULTS_CAP))

    service = _build_service()
    listing = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )

    summaries: list[dict[str, str]] = []
    for ref in listing.get("messages", []):
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=ref["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
        headers = msg.get("payload", {}).get("headers", [])
        summaries.append(
            {
                "id": msg.get("id", ""),
                "thread_id": msg.get("threadId", ""),
                "from": _header(headers, "From"),
                "subject": _header(headers, "Subject"),
                "date": _header(headers, "Date"),
                "snippet": msg.get("snippet", ""),
            }
        )
    return summaries
