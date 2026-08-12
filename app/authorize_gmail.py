"""One-time helper to mint a read-only Gmail token for the agent.

Run this **once, locally** (it needs a browser for Google's consent screen).
It performs the OAuth installed-app flow with only the ``gmail.readonly``
scope and prints the resulting authorised-user JSON — copy that into the
``GMAIL_TOKEN_JSON`` env var (e.g. your gitignored ``.env``) so the agent can
authenticate at runtime. See README → Gmail credentials.

Usage:

    python authorize_gmail.py [path/to/client_secrets.json]

The client secrets file is the OAuth *Desktop app* client you download from
the Google Cloud console. It defaults to ``credentials.json`` in the current
directory, or the path in ``GMAIL_OAUTH_CLIENT_SECRETS``. Neither the client
secrets nor the emitted token is written to the repo — both are gitignored /
printed to stdout only.
"""

from __future__ import annotations

import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from gmail_triage_agent.gmail_client import SCOPES


def main(argv: list[str]) -> int:
    secrets_path = (
        argv[1]
        if len(argv) > 1
        else os.environ.get("GMAIL_OAUTH_CLIENT_SECRETS", "credentials.json")
    )
    if not os.path.exists(secrets_path):
        print(
            f"Client secrets file not found: {secrets_path}\n"
            "Download the OAuth 'Desktop app' client JSON from the Google "
            "Cloud console and pass its path (or set "
            "GMAIL_OAUTH_CLIENT_SECRETS).",
            file=sys.stderr,
        )
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(secrets_path, list(SCOPES))
    # access_type=offline + prompt=consent guarantees a refresh_token, which is
    # what lets the agent keep authenticating without re-consenting.
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent"
    )

    print(
        "\n=== Gmail read-only token ===\n"
        "Set the following as GMAIL_TOKEN_JSON (single line, e.g. in .env):\n",
        file=sys.stderr,
    )
    # The token JSON is the only thing on stdout, so it can be piped/captured.
    print(creds.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
