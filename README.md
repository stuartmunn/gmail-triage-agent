# Gmail Triage Agent

An agent that watches a Gmail inbox and triages incoming mail — classifying
and prioritizing messages, and notifying via Telegram when something needs
attention — so the inbox stays manageable without manual sorting.

Built on the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview).
The build is scoped in phases with explicit trust boundaries; see
[`CLAUDE.md`](./CLAUDE.md). **Phase 1 (current) is read-only:** Gmail read
access only, notification via Telegram, no inbox mutations of any kind.

## Status

Early scaffold. Development is tracked in Jira project
[GTA](https://stuartmunn.atlassian.net/browse/GTA).

## Folder layout

```
.
├── app/                  # All application code — the Docker build context
│   ├── agent.py          # Entry point
│   ├── gmail_triage_agent/   # Package
│   ├── tests/            # Tests (dev-time; excluded from the image)
│   ├── pyproject.toml    # Dependencies — single source of truth
│   ├── Dockerfile        # Build context is app/, not the repo root
│   └── .dockerignore
├── data/                 # Live, host-editable data (senders list, logs),
│                         #   bind-mounted into the container at runtime
├── docker-compose.yml    # Repo root; builds ./app, mounts ./data
├── CLAUDE.md             # Project guidance   ── repo-root/dev files,
├── CODING_STANDARDS.md   # Conventions        ── never copied into the image
└── README.md
```

`CLAUDE.md`, `CODING_STANDARDS.md`, and `README.md` deliberately live at the
repo root, outside `app/`, so they never end up in the image.

## Running

Credentials are always supplied at runtime (env vars), never committed or
baked into the image. Phase 1 needs `ANTHROPIC_API_KEY`; later stories add
the Gmail and Telegram secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).

### With Docker (recommended)

```bash
# Optional: put secrets in a gitignored .env at the repo root
#   ANTHROPIC_API_KEY=...
# (or export them in your shell — docker-compose passes them through)

docker compose up --build
```

This builds the image from `./app` and bind-mounts `./data` into the
container. The agent runs once and exits (scheduling is a later story).

### Locally (without Docker)

```bash
cd app
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python agent.py
```

The SDK drives the agent by spawning the
[Claude Code CLI](https://docs.claude.com/en/api/agent-sdk/overview), so a
local run also needs Node.js 18+ and the CLI on your `PATH`
(`npm install -g @anthropic-ai/claude-code`). The Docker image bundles both.

## Gmail credentials (read-only)

The agent reads Gmail through the Gmail API with the **`gmail.readonly`**
scope only — no send, modify, delete, or label access (Phase 1 trust
boundary). Credentials are supplied at runtime via the `GMAIL_TOKEN_JSON`
env var and are never committed.

One-time setup (needs a browser, done on your machine):

1. In the [Google Cloud console](https://console.cloud.google.com/), create
   a project and **enable the Gmail API**.
2. Configure the OAuth consent screen (**External** is fine for a personal
   account; add your Gmail address as a **test user**).
3. Create an **OAuth client ID** of type **Desktop app** and download its
   JSON — save it as `credentials.json` (gitignored; never commit it).
4. Mint a read-only token:
   ```bash
   cd app
   pip install -e ".[dev]"          # if not already installed
   python authorize_gmail.py path/to/credentials.json
   ```
   A browser opens for consent (you'll see it request **read-only** access).
   The script prints the authorised-user JSON to stdout.
5. Put that JSON into `GMAIL_TOKEN_JSON` — e.g. in a gitignored `.env` at the
   repo root (one line):
   ```
   GMAIL_TOKEN_JSON={"token": "...", "refresh_token": "...", ...}
   ```
   `docker compose` passes it through to the container automatically.

**Refresh / regenerate:** the token includes a long-lived `refresh_token`,
so the agent renews access automatically — no periodic action needed. If the
token is revoked (e.g. via your Google Account's *Third-party access*), or you
need to change scope, just re-run `authorize_gmail.py` and replace
`GMAIL_TOKEN_JSON`. The agent refuses to start if the token carries any scope
beyond `gmail.readonly`.

## Telegram notifications

The agent notifies you via a Telegram bot — **send-only, to one fixed chat**.
It never reads Telegram messages, and the destination chat ID always comes
from `TELEGRAM_CHAT_ID` (never from the message content or the model), so the
notification can't be redirected.

One-time setup:

1. In Telegram, message [@BotFather](https://t.me/BotFather), send
   `/newbot`, and follow the prompts to get a **bot token**.
2. Start a chat with your new bot and send it any message (a bot can't
   message you until you've spoken to it first).
3. Find your **chat ID**: open
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and
   read `result[].message.chat.id` (it's the `id` under `chat`).
4. Set both as env vars — e.g. in the gitignored `.env` at the repo root:
   ```
   TELEGRAM_BOT_TOKEN=<your-bot-token>
   TELEGRAM_CHAT_ID=<your-chat-id>
   ```
   `docker compose` passes them through automatically. Neither is ever
   committed.

To verify quickly from a local checkout:

```bash
cd app
python -c "from gmail_triage_agent.telegram_client import send_message; send_message('Gmail Triage Agent test ✅')"
```

## Development

Lint before pushing:

```bash
ruff check app/
```

See [`CLAUDE.md`](./CLAUDE.md) and [`CODING_STANDARDS.md`](./CODING_STANDARDS.md)
for workflow (branch → PR → PR-Agent review) and conventions.
