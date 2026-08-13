# Gmail Triage Agent — Phase 1 image.
#
# Build context is app/ (see docker-compose.yml / .dockerignore), so only the
# application lives in the image. Repo-level dev files (CLAUDE.md,
# CODING_STANDARDS.md, README.md) stay outside the context and are never
# copied in. Live data (known-senders list, logs) is bind-mounted at runtime,
# not baked in — see docker-compose.yml.
#
# The Python claude-agent-sdk drives the agent by spawning the Claude Code CLI
# (a Node package), so the image ships Python 3.12 + Node.js 22 + the CLI.
# Credentials (ANTHROPIC_API_KEY, and later Gmail/Telegram secrets) are passed
# in at runtime as env vars — never ARG/ENV-baked here.

# Node.js comes from the official image (both stages are Debian bookworm, so
# the runtime is ABI-compatible). Copying the binary avoids piping a remote
# setup script to a root shell during the build — the source is a trusted,
# digest-pinnable image and apt/npm never fetch-and-execute untrusted code.
FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm

# Bring Node + npm across from the official image and wire up the usual
# entry-point symlinks. libstdc++6 is needed by the node binary.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# The SDK launches the Claude Code CLI, so install it globally.
RUN npm install -g @anthropic-ai/claude-code \
    && npm cache clean --force

# Non-root user. uid 1000 matches the typical host user so writes to the
# bind-mounted data/ dir aren't blocked by ownership.
RUN useradd --create-home --uid 1000 appuser

# Non-root user can't write bytecode caches into the root-owned /app, and we
# want unbuffered stdout so container logs stream in real time. GTA_DATA_DIR
# points at the bind-mounted data dir (known-senders, logs) so it resolves
# correctly even when run without compose.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GTA_DATA_DIR=/app/data

WORKDIR /app

# Install Python deps from pyproject (single source of truth for the SDK pin).
# Copy the source first so the local package builds; deps are small enough
# that a dedicated dependency-only layer isn't worth the extra plumbing.
COPY --chown=appuser:appuser . .
RUN pip install --no-cache-dir .

USER appuser

# The CLI caches config under $HOME/.claude; appuser owns its home so that
# works without root.
ENV HOME=/home/appuser

CMD ["python", "agent.py"]
