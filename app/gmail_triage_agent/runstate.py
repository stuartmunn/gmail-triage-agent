"""Persist the last-successful-run timestamp and derive the triage window.

Scheduling (GTA-10) runs the agent every few hours. To triage only *new*
mail, each run records when it started and, **on success**, persists that as
the new "last successful run". The next run then searches Gmail for messages
that arrived since then. A failed run does not advance the marker, so the
same window is retried next time — no mail is silently skipped.

State lives under the bind-mounted data dir (``data/state/last_success``), so
it survives container restarts and rebuilds.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from gmail_triage_agent.triage import data_dir

_STATE_RELPATH = ("state", "last_success")

# First run (no marker yet) looks back a bounded window rather than the whole
# mailbox. Kept modest so the very first scheduled run isn't a huge triage.
BOOTSTRAP_QUERY = "in:inbox newer_than:1d"


def now_epoch() -> int:
    return int(time.time())


def state_path() -> Path:
    return data_dir().joinpath(*_STATE_RELPATH)


def read_last_success() -> int | None:
    """Return the last successful run time (epoch seconds), or None if there
    is no valid marker yet (first run, or a corrupt/empty file)."""
    try:
        raw = state_path().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def write_last_success(epoch: int) -> None:
    """Persist ``epoch`` as the last successful run time, atomically.

    Writes to a unique temp file in the same directory, then ``os.replace`` —
    atomic on POSIX and safe even if two writers ever raced (each gets its own
    temp, so neither can corrupt the other's partial write).
    """
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(str(int(epoch)))
        os.replace(tmp_name, path)  # never leaves a half-written marker
    except BaseException:  # noqa: BLE001 — clean up the temp on *any* failure, then re-raise
        # Don't leave an orphan temp behind on any failure.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def incremental_query(last_success: int | None) -> str:
    """Gmail query for the window to triage this run.

    ``in:inbox after:<epoch>`` for the window since the last success; the
    bootstrap window on the first run. Gmail's ``after:`` accepts epoch
    seconds.
    """
    if last_success is None:
        return BOOTSTRAP_QUERY
    return f"in:inbox after:{int(last_success)}"
