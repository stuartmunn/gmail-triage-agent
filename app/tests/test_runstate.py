"""Tests for the scheduling run-state (GTA-10).

Cover the acceptance-criteria behaviours: the last-success marker round-trips
and survives (persisted to a file), a missing/corrupt marker is treated as
"no marker yet", and the incremental query targets mail since the marker (or
a bootstrap window on the first run).
"""

from gmail_triage_agent import runstate


def _point_state_at(tmp_path, monkeypatch):
    monkeypatch.setenv("GTA_DATA_DIR", str(tmp_path))


def test_write_then_read_roundtrips(tmp_path, monkeypatch):
    _point_state_at(tmp_path, monkeypatch)
    runstate.write_last_success(1_700_000_000)
    assert runstate.read_last_success() == 1_700_000_000
    # Persisted to a real file under the data dir (survives a restart).
    assert runstate.state_path().exists()


def test_read_missing_returns_none(tmp_path, monkeypatch):
    _point_state_at(tmp_path, monkeypatch)
    assert runstate.read_last_success() is None


def test_read_corrupt_returns_none(tmp_path, monkeypatch):
    _point_state_at(tmp_path, monkeypatch)
    path = runstate.state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-a-number", encoding="utf-8")
    assert runstate.read_last_success() is None


def test_write_creates_missing_parents(tmp_path, monkeypatch):
    _point_state_at(tmp_path, monkeypatch)
    # state/ subdir does not exist yet — write must create it.
    runstate.write_last_success(runstate.now_epoch())
    assert runstate.state_path().exists()


def test_incremental_query_first_run_uses_bootstrap():
    assert runstate.incremental_query(None) == runstate.BOOTSTRAP_QUERY


def test_incremental_query_uses_after_since_last_success():
    assert runstate.incremental_query(1_700_000_000) == "in:inbox after:1700000000"
