# Known senders

Template for `data/known-senders.md` — copy this file to `known-senders.md`
in the same directory and edit it with your real contacts:

```bash
cp data/known-senders.example.md data/known-senders.md
```

`known-senders.md` is **gitignored** (it holds personal contacts, so it stays
off GitHub) and is **read fresh on every run** — edit it on the host any time
and the next run picks it up, no rebuild or restart needed.

This is a **living list**: add people/domains as the agent gets triage calls
wrong. It's free-form context for the triage skill to reason over, not a rigid
schema — plain lines and notes are fine. The agent treats mail from these
senders as higher-signal (see `app/gmail-triage/SKILL.md`).

---

## People who matter (examples — replace these)

- Jane Example <jane@example.com> — partner; anything from her is actionable
- Sam Colleague <sam@work-example.com> — manager; task/deadline mail matters

## Work domains

- @work-example.com — colleagues; real asks/deadlines are actionable, but
  the automated all-staff newsletter from this domain is not

## Important automated senders

- @mybank-example.com — bank; statements and anything with a due date
- noreply@council-example.gov — bills / renewals with deadlines

## Notes

- Being on this list raises signal; it does not by itself make every message
  actionable — a marketing blast from a known domain is still not actionable.
