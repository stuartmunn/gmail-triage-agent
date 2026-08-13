# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See also [`CODING_STANDARDS.md`](./CODING_STANDARDS.md) for accumulated
Python/agent-SDK conventions — read it alongside this file. It grows
rule-by-rule as PR Agent flags repeated or avoidable mistakes (see
Working Practices → Code review below).

## Project Overview

Gmail Triage Agent watches a Gmail inbox and triages incoming mail —
classifying, prioritizing, and (per phase — see below) acting on messages —
so the inbox stays manageable without manual sorting. Built on the
[Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview).

## Phases

The build is scoped in phases, each with its own trust boundary. **Do not
build ahead of the current phase** — a later phase's tools/scopes are not
implicitly available just because the code would be easy to write.

### Phase 1 — Read-only triage (current)

Read-only Gmail monitoring, triage against a skill, Telegram notification.
**No write scopes of any kind.**

- Gmail access is **read-only** (search/read messages and threads only —
  no label, archive, send, draft, or delete).
- Triage logic runs against a Claude skill; output is a notification, not an
  inbox mutation.
- Notification is **Telegram-only** — no email replies, no auto-labeling,
  no other side effects.
- The triage models get **no tools**: each email is classified via the
  Anthropic Messages API (structured decision + confidence; Haiku first,
  Sonnet on uncertainty), and the model cannot act. Gmail is read via the
  read-only Gmail client and Telegram is sent via the send-only client (fixed
  chat ID from env) — both from the pipeline in `agent.py`, never the model.
  No other capability is wired in.

### Phase 2 — not yet scoped

Not yet defined. Do not assume scope (e.g. labeling, archiving, drafting)
until a story defines it.

### Phase 3 — not yet scoped

Not yet defined.

## Trust Boundaries

This is the source of truth for what the agent is allowed to touch at each
phase (Jira epic GTA-1 defers to this file). When a story's "Trust boundary
notes" section grants a tool, that grant is scoped to that story's phase —
it does not carry forward to future phases automatically, and it does not
imply adjacent tools (e.g. `gmail_search` grants read, never write).

- **Gmail**: read-only in Phase 1. No send, label, archive, trash, or draft
  until a later phase explicitly grants it.
- **Telegram**: outbound notification only, to a single fixed chat ID read
  from env — never a user-supplied or dynamic chat ID.
- **No other integrations** (e.g. Paperless, Calendar) unless a story
  explicitly grants them.

## Tech Stack

- **Language**: Python 3.12
- **Model access**: [Claude API](https://docs.claude.com/en/api/overview) — the Anthropic Messages API (`anthropic` SDK), structured outputs, Haiku→Sonnet routing (no tools registered on the models)
- **Email**: Gmail API (read-only scope in Phase 1)
- **Notifications**: Telegram Bot API

## Working Practices

### Branching — always required

Every change, however small, must be made on a new branch and submitted as
a GitHub pull request. Never commit directly to `main` — branch protection
enforces this (PR required, no force-pushes, enforced for admins too).

Branch naming convention: `feature/<slug>`, `fix/<slug>`, `chore/<slug>`.

> **Bootstrap exception (historical):** GTA-2 (initial repo creation) was
> pushed directly to `main`, because an empty repo has no base branch to
> open a PR against. That was a one-off; everything from GTA-3 onward
> follows the branch → PR flow above.

### Code review — PR Agent runs on every PR

Every PR is reviewed automatically by **PR Agent**. After opening a PR:

1. Wait a few minutes, then check the PR for PR Agent's comments.
2. Triage each comment as genuine or a false positive — use judgement,
   don't blindly action everything a bot says.
3. Fix what's genuinely worth fixing, retest locally where possible, and
   push the updates to the PR.
4. Comment on the PR documenting what PR Agent raised, what was actioned,
   and what was dismissed and why.

### Story workflow

1. **Read the Jira story** (project key **GTA** on `stuartmunn.atlassian.net`).
   Stories are authored by the business analyst — **never create Jira
   stories/epics**, even if the backlog looks incomplete; implement against
   what exists and flag gaps to Stuart instead.
2. Develop on a feature branch named `GTA-<number>-short-description`.
   Transition the story to **In Progress**.
3. Test locally wherever possible before opening a PR.
4. Commit, push, open a PR referencing the story.
5. Follow the PR Agent review process above.
6. Keep the Jira story updated — status and a comment summarizing what was
   done, any decisions made, and any limitations.
7. **Never merge the PR.** Merging requires Stuart's explicit consent,
   every time.

### Code quality

- Model output (Gmail content, classification results) is untrusted —
  never execute or interpolate it into shell commands, file paths, or
  templated HTML without validation/escaping.
- Every tool registered on the agent must be deliberately scoped in
  `allowed_tools` — no wildcard/broad grants.
- **No secrets, tokens, keys, or credentials** in `CODING_STANDARDS.md` or
  any other file that reaches GitHub — env vars only, never inlined as
  examples (not even as plausible-looking placeholder values).
- See [`CODING_STANDARDS.md`](./CODING_STANDARDS.md) for further
  Python/agent-SDK conventions; add a rule there (not here) after a PR
  Agent comment identifies a repeated or avoidable mistake, before
  merging that PR.

## Testing

No automated tests yet. Add them as the codebase grows past the skeleton
stage; until then, manual runs (`python agent.py`) are the verification
path noted in each story's acceptance criteria.

## Who You're Working With

Stuart is the reviewer and the only person who authorises merges.
