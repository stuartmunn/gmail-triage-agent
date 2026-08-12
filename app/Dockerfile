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

FROM python:3.12-slim-bookworm

# Node.js 22 (matches host) so the SDK can launch the Claude Code CLI.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. uid 1000 matches the typical host user so writes to the
# bind-mounted data/ dir aren't blocked by ownership.
RUN useradd --create-home --uid 1000 appuser

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
