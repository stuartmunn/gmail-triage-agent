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

## Development

Lint before pushing:

```bash
ruff check app/
```

See [`CLAUDE.md`](./CLAUDE.md) and [`CODING_STANDARDS.md`](./CODING_STANDARDS.md)
for workflow (branch → PR → PR-Agent review) and conventions.
