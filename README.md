# Gmail Triage Agent

An agent that triages incoming Gmail: classifies, labels, prioritizes, and
acts on messages (archive, label, draft replies, notify) so the inbox stays
manageable without manual sorting.

## Status

Early scaffold — no functionality yet. Development is tracked in Jira
project [GTA](https://stuartmunn.atlassian.net/browse/GTA).

## Stack

Python 3.12+.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```
