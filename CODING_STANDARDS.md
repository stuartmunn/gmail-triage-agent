# Coding Standards

Project-specific conventions for Gmail Triage Agent, kept separate from
`CLAUDE.md` so this file can grow rule-by-rule without cluttering the
higher-level project guidance. Claude Code reads both automatically (see
`CLAUDE.md`).

## Process — how this file grows

This file starts seeded with the obvious conventions already implied by the
repo (layout, tooling, phase boundaries). Beyond that:

1. When **PR Agent** flags something on a PR — a repeated pattern, a
   style issue, an avoidable mistake — triage it as usual (genuine vs.
   false positive, per `CLAUDE.md`'s PR Agent workflow).
2. If it's genuine and generalizable (not a one-off typo), add a rule here
   **before merging** that PR, so the same mistake isn't repeated on the
   next one.
3. Keep rules short and concrete — a sentence and, where useful, a
   do/don't example. This file is a checklist, not prose documentation.
4. Do not retroactively mine old PR history for rules (out of scope per
   GTA-5) — only add rules going forward as PR Agent actually raises them.

## Secrets and credentials

- **Never** inline secrets, tokens, API keys, or credentials in this file,
  `CLAUDE.md`, or any other file that reaches GitHub — env vars only.
- No example values that look like real credentials either (e.g. a
  plausible-looking API key in a code sample) — use obvious placeholders
  such as `<YOUR_API_KEY>` or `os.environ["TELEGRAM_BOT_TOKEN"]`.
- `credentials.json`, `token.json`, and `.env*` are gitignored — keep it
  that way; don't add exceptions.

## Python conventions

- **Python 3.12+**, matching `pyproject.toml`'s `requires-python`.
- All application code lives under `app/` (the Docker build context): the
  entry point is `app/agent.py`, the package is `app/gmail_triage_agent/`,
  tests are `app/tests/`, and `app/pyproject.toml` is the single source of
  truth for dependencies (see its `[tool.setuptools.packages.find]`).
  Repo-root files (`CLAUDE.md`, `CODING_STANDARDS.md`, `README.md`,
  `docker-compose.yml`) stay **outside** `app/` — dev/meta only, never
  copied into the image.
- Live, host-editable data (e.g. `known-senders.md`, logs) lives under
  `data/` at repo root, bind-mounted into the container — never baked into
  the image.
- Lint/format with **ruff** (already a dev dependency) — run it before
  pushing:
  ```bash
  ruff check app/
  ```
- Test with **pytest** (already a dev dependency). No suite exists yet
  (see `CLAUDE.md` → Testing) — add tests as functionality lands.
- Use type hints on function signatures for new code; prefer standard
  library `dataclasses`/`typing` over ad-hoc dicts for structured data.
- Prefer explicit imports (`from x import y`) over wildcard imports.

## Agent SDK conventions

- Every tool registered on the agent must be deliberately named and
  scoped in `allowed_tools` — no wildcard/broad grants (see `CLAUDE.md` →
  Trust Boundaries). This is a hard rule, not a style preference.
- Treat all model output (Gmail content, classification results) as
  untrusted input: never execute it, and never interpolate it into shell
  commands, file paths, or templated HTML without validation/escaping
  (see `CLAUDE.md` → Code quality).
- Don't build tools or scopes ahead of the current phase — check
  `CLAUDE.md` → Phases before adding a new capability.

## Git / PR hygiene

- Branch names: `GTA-<number>-short-description` for story work,
  `feature/<slug>` / `fix/<slug>` / `chore/<slug>` otherwise.
- Keep commits scoped to the story/change at hand — avoid drive-by
  refactors in the same PR unless the story calls for it.
