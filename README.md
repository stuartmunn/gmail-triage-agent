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
│   ├── gmail-triage/     # Triage skill (SKILL.md) — ships with the app
│   ├── tests/            # Tests (dev-time; excluded from the image)
│   ├── pyproject.toml    # Dependencies — single source of truth
│   ├── Dockerfile        # Build context is app/, not the repo root
│   └── .dockerignore
├── data/                 # Live, host-editable data, bind-mounted at runtime
│   └── known-senders.md  #   (gitignored; copy from known-senders.example.md)
├── docker-compose.yml    # Repo root; builds ./app, mounts ./data
├── CLAUDE.md             # Project guidance   ── repo-root/dev files,
├── CODING_STANDARDS.md   # Conventions        ── never copied into the image
└── README.md
```

`CLAUDE.md`, `CODING_STANDARDS.md`, and `README.md` deliberately live at the
repo root, outside `app/`, so they never end up in the image.

## Running

Credentials are always supplied at runtime (env vars), never committed or
baked into the image. Put them all in a gitignored `.env` at the repo root —
see **Configuration** below.

### With Docker (recommended)

```bash
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

## Configuration

All secrets live in a single gitignored `.env` at the **repo root** (next to
`docker-compose.yml`); `docker compose` passes them through to the container.
Nothing is committed or baked into the image.

```
ANTHROPIC_API_KEY=<your-key>
GMAIL_TOKEN_JSON=<one-line JSON — see "Gmail credentials" below>
TELEGRAM_BOT_TOKEN=<from BotFather — see "Telegram notifications" below>
TELEGRAM_CHAT_ID=<your chat id>
```

- `GMAIL_TOKEN_JSON` must be the token JSON on a **single line, unquoted**:
  `docker compose` keeps the value verbatim, so surrounding quotes would be
  taken literally.
- How to obtain each value is in the two sections below. Then launch with
  `docker compose up --build` (see **Running**).

### Python environment (venv)

The one-time helper scripts (`authorize_gmail.py`, the local test
one-liners) run **outside** Docker, so they need the dependencies in a
virtualenv:

```bash
cd app
python3 -m venv .venv
```

Activation differs by shell:

- **bash/zsh (Linux/macOS):** `source .venv/bin/activate` then `pip install -e .`
- **Windows PowerShell:** `.\.venv\Scripts\Activate.ps1` then `pip install -e .`
  — or skip activation and call the venv Python directly:
  `.\.venv\Scripts\python.exe -m pip install -e .`

On Debian/Ubuntu you may first need `sudo apt install python3.12-venv` (the
system Python is PEP-668 "externally managed" — install into the venv, never
with `--break-system-packages`).

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
3. Create an **OAuth client ID** of type **Desktop app** (required — a
   *Web application* client rejects the loopback redirect with
   `redirect_uri_mismatch`) and download its JSON. A Desktop client's JSON
   starts with `{"installed": …}`; a Web one starts with `{"web": …}`. Keep
   it gitignored; never commit it.
4. Mint a read-only token using the venv from **Configuration → Python
   environment**:
   ```bash
   # from app/, inside the activated venv (Windows: use .\.venv\Scripts\python.exe)
   python authorize_gmail.py path/to/credentials.json
   ```
   A browser opens for consent (you'll see it request **read-only** access).
   The script prints the authorised-user JSON as its **last line** (stdout);
   the guidance above it goes to stderr.
5. Put that JSON into `GMAIL_TOKEN_JSON` — e.g. in a gitignored `.env` at the
   repo root (one line):
   ```
   GMAIL_TOKEN_JSON={"token": "...", "refresh_token": "...", ...}
   ```
   `docker compose` passes it through to the container automatically.

> **Headless / remote servers:** `authorize_gmail.py` needs a browser for the
> consent screen, which a headless box (e.g. a home server) doesn't have. Run
> the mint step on any machine **with a browser** (e.g. your laptop), then
> copy just the printed `GMAIL_TOKEN_JSON` into the server's `.env`. The token
> is portable, and `credentials.json` never needs to reach the server.

> **Troubleshooting `redirect_uri_mismatch`:** the OAuth client is a *Web
> application* type — recreate it as **Desktop app** (step 3).

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

To verify quickly from a local checkout (inside the venv from
**Configuration → Python environment**, with the two Telegram vars set):

```bash
cd app
python -c "from gmail_triage_agent.telegram_client import send_message; send_message('Gmail Triage Agent test ✅')"
```

## Triage rules

What counts as "needs attention" is defined in
[`app/gmail-triage/SKILL.md`](app/gmail-triage/SKILL.md) — plain-language
guidance the agent reasons over (named people and direct asks outrank
newsletters; deadlines and bills are flagged; FYI threads and marketing are
not). It ships with the app. It's a **living document**: when the agent
misjudges a message, tune the rules there rather than working around them.

Your personal contacts live in `data/known-senders.md`, separate from the
rules so you can edit it without touching code or rebuilding. It's
**gitignored** (keeps real contacts off GitHub) and **read fresh every run**,
so host edits take effect on the next run. Create it from the template:

```bash
cp data/known-senders.example.md data/known-senders.md
# then edit data/known-senders.md with your real people/domains
```

If it's absent, the agent still runs and treats every sender as unknown.

**Silence when nothing's actionable:** a run that finds nothing worth your
attention sends **no** Telegram message at all — no all-clear, no digest.

Each run triages a recent window of mail (default `in:inbox newer_than:1d`);
override with the `GTA_SEARCH_QUERY` env var. (Incremental "since last run"
windows come in GTA-10.)

## Development

Lint before pushing:

```bash
ruff check app/
```

See [`CLAUDE.md`](./CLAUDE.md) and [`CODING_STANDARDS.md`](./CODING_STANDARDS.md)
for workflow (branch → PR → PR-Agent review) and conventions.
