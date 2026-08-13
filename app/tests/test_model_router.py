"""Tests for the Haiku-first / Sonnet-on-uncertainty router (GTA-11).

The classifier is injected, so these exercise the escalation logic, threshold
handling, and escalation logging without any network calls. The real Messages
API path (``classify`` / ``_build_client``) is not exercised here.
"""

import json

import pytest

from gmail_triage_agent import model_router
from gmail_triage_agent.model_router import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    HAIKU_MODEL,
    SONNET_MODEL,
    THRESHOLD_ENV,
    TriageResult,
    read_threshold,
    triage_messages,
)

_MSG = {
    "id": "m1",
    "from": "Dana <dana@example.com>",
    "subject": "Invoice due Friday",
    "date": "Mon, 1 Jan 2026 09:00:00 +0000",
    "snippet": "please review",
}


def _make_classifier(by_model):
    """A fake classifier returning a preset result per model, recording calls."""
    calls = []

    def _classify(model, system_prompt, user_prompt):
        calls.append(model)
        return by_model[model]

    _classify.calls = calls
    return _classify


def test_below_threshold_escalates_to_sonnet():
    haiku = TriageResult("silent", 0.4, "unsure", HAIKU_MODEL)
    sonnet = TriageResult("notify", 0.9, "actually important", SONNET_MODEL)
    classifier = _make_classifier({HAIKU_MODEL: haiku, SONNET_MODEL: sonnet})

    verdicts = triage_messages(
        [_MSG], "RULES", None, threshold=0.7, classifier=classifier
    )

    assert classifier.calls == [HAIKU_MODEL, SONNET_MODEL]
    v = verdicts[0]
    assert v.escalated is True
    assert v.model == SONNET_MODEL  # Sonnet gives the final verdict
    assert v.decision == "notify"
    assert v.confidence == 0.9
    assert v.reason == "actually important"
    assert v.haiku_confidence == 0.4


def test_at_or_above_threshold_stays_haiku():
    haiku = TriageResult("notify", 0.8, "clear", HAIKU_MODEL)
    classifier = _make_classifier({HAIKU_MODEL: haiku})

    verdicts = triage_messages(
        [_MSG], "RULES", None, threshold=0.7, classifier=classifier
    )

    assert classifier.calls == [HAIKU_MODEL]  # no Sonnet call
    v = verdicts[0]
    assert v.escalated is False
    assert v.model == HAIKU_MODEL
    assert v.decision == "notify"
    assert v.confidence == 0.8


def test_confidence_equal_to_threshold_does_not_escalate():
    # Escalation is strictly below the threshold.
    haiku = TriageResult("silent", 0.7, "borderline", HAIKU_MODEL)
    classifier = _make_classifier({HAIKU_MODEL: haiku})

    verdicts = triage_messages(
        [_MSG], "RULES", None, threshold=0.7, classifier=classifier
    )

    assert classifier.calls == [HAIKU_MODEL]
    assert verdicts[0].escalated is False


def test_verdict_carries_message_identity():
    haiku = TriageResult("silent", 0.95, "newsletter", HAIKU_MODEL)
    classifier = _make_classifier({HAIKU_MODEL: haiku})

    v = triage_messages(
        [_MSG], "RULES", None, threshold=0.7, classifier=classifier
    )[0]

    assert v.message_id == "m1"
    assert v.sender == "Dana <dana@example.com>"
    assert v.subject == "Invoice due Friday"


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, DEFAULT_CONFIDENCE_THRESHOLD),
        ("", DEFAULT_CONFIDENCE_THRESHOLD),
        ("0.9", 0.9),
        ("0", 0.0),
        ("1", 1.0),
        ("not-a-number", DEFAULT_CONFIDENCE_THRESHOLD),
        ("1.5", DEFAULT_CONFIDENCE_THRESHOLD),
        ("-0.1", DEFAULT_CONFIDENCE_THRESHOLD),
    ],
)
def test_read_threshold(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv(THRESHOLD_ENV, raising=False)
    else:
        monkeypatch.setenv(THRESHOLD_ENV, raw)
    assert read_threshold() == expected


def test_escalation_writes_jsonl_record_without_email_body(tmp_path, monkeypatch):
    monkeypatch.setenv("GTA_DATA_DIR", str(tmp_path))
    haiku = TriageResult("silent", 0.2, "unsure", HAIKU_MODEL)
    sonnet = TriageResult("notify", 0.95, "bill due", SONNET_MODEL)
    classifier = _make_classifier({HAIKU_MODEL: haiku, SONNET_MODEL: sonnet})

    msg = dict(_MSG, subject="Pay up", snippet="SECRET-BODY-TEXT")
    triage_messages([msg], "RULES", None, threshold=0.7, classifier=classifier)

    record_file = tmp_path / "logs" / "escalations.jsonl"
    assert record_file.exists()
    line = record_file.read_text(encoding="utf-8").strip()
    record = json.loads(line)

    assert record["from_model"] == HAIKU_MODEL
    assert record["to_model"] == SONNET_MODEL
    assert record["final_decision"] == "notify"
    assert record["subject"] == "Pay up"
    assert record["haiku_confidence"] == 0.2
    # The email snippet/body must never reach the log.
    assert "SECRET-BODY-TEXT" not in line


def test_no_escalation_writes_no_record(tmp_path, monkeypatch):
    monkeypatch.setenv("GTA_DATA_DIR", str(tmp_path))
    haiku = TriageResult("notify", 0.9, "clear", HAIKU_MODEL)
    classifier = _make_classifier({HAIKU_MODEL: haiku})

    triage_messages([_MSG], "RULES", None, threshold=0.7, classifier=classifier)

    assert not (tmp_path / "logs" / "escalations.jsonl").exists()


def test_read_threshold_is_module_level_helper():
    # Guard against accidental rename — agent.py calls this name.
    assert callable(model_router.read_threshold)
