"""Tests for cost accounting (GTA-12).

Exercise pricing config resolution, per-email/per-model costing, and the run
records — no network calls (verdicts are built directly). Cost accounting must
never fail a run and must never leak email content into the logs; both are
covered here.
"""

import json

from gmail_triage_agent.cost import (
    ModelPrice,
    cost_for_result,
    email_cost,
    load_pricing,
    record_run,
)
from gmail_triage_agent.model_router import (
    HAIKU_MODEL,
    SONNET_MODEL,
    MessageVerdict,
    TriageResult,
)


def _result(model, input_tokens, output_tokens):
    return TriageResult(
        decision="silent",
        confidence=0.9,
        reason="x",
        model=model,
        usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
    )


def _verdict(results, *, escalated, sender="Dana <dana@example.com>", subject="Hi"):
    final = results[-1]
    return MessageVerdict(
        message_id="m1",
        sender=sender,
        subject=subject,
        decision=final.decision,
        confidence=final.confidence,
        reason=final.reason,
        model=final.model,
        escalated=escalated,
        haiku_confidence=results[0].confidence,
        results=results,
    )


# --- pricing config ----------------------------------------------------------


def test_load_pricing_defaults_when_file_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("GTA_DATA_DIR", str(tmp_path))
    pricing = load_pricing()
    assert pricing[HAIKU_MODEL] == ModelPrice(1.00, 5.00)
    assert pricing[SONNET_MODEL] == ModelPrice(2.00, 10.00)


def test_load_pricing_override_merges_over_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("GTA_DATA_DIR", str(tmp_path))
    # Override only Sonnet (its intro rate reverts) — Haiku keeps the default.
    (tmp_path / "pricing.json").write_text(
        json.dumps({SONNET_MODEL: {"input_per_mtok": 3.0, "output_per_mtok": 15.0}}),
        encoding="utf-8",
    )
    pricing = load_pricing()
    assert pricing[SONNET_MODEL] == ModelPrice(3.0, 15.0)
    assert pricing[HAIKU_MODEL] == ModelPrice(1.00, 5.00)  # default preserved


def test_load_pricing_malformed_file_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("GTA_DATA_DIR", str(tmp_path))
    (tmp_path / "pricing.json").write_text("{ not json", encoding="utf-8")
    pricing = load_pricing()
    assert pricing[HAIKU_MODEL] == ModelPrice(1.00, 5.00)


def test_load_pricing_skips_bad_entry_keeps_good_one(tmp_path, monkeypatch):
    monkeypatch.setenv("GTA_DATA_DIR", str(tmp_path))
    (tmp_path / "pricing.json").write_text(
        json.dumps(
            {
                HAIKU_MODEL: {"input_per_mtok": 9.0, "output_per_mtok": 9.0},
                SONNET_MODEL: {"input_per_mtok": "oops"},  # malformed
            }
        ),
        encoding="utf-8",
    )
    pricing = load_pricing()
    assert pricing[HAIKU_MODEL] == ModelPrice(9.0, 9.0)  # good entry applied
    assert pricing[SONNET_MODEL] == ModelPrice(2.00, 10.00)  # bad entry -> default


# --- costing math ------------------------------------------------------------


def test_cost_for_result_math():
    pricing = {HAIKU_MODEL: ModelPrice(1.0, 5.0)}
    # 1,000,000 in @ $1/MTok + 2,000,000 out @ $5/MTok = $1 + $10 = $11.
    mc = cost_for_result(_result(HAIKU_MODEL, 1_000_000, 2_000_000), pricing)
    assert mc.usd == 11.0
    assert mc.input_tokens == 1_000_000
    assert mc.output_tokens == 2_000_000


def test_cost_for_result_missing_usage_is_zero_not_crash():
    pricing = {HAIKU_MODEL: ModelPrice(1.0, 5.0)}
    result = TriageResult("silent", 0.9, "x", HAIKU_MODEL, usage=None)
    mc = cost_for_result(result, pricing)
    assert mc.usd == 0.0
    assert mc.input_tokens == 0 and mc.output_tokens == 0


def test_cost_for_result_none_token_values_treated_as_zero():
    pricing = {HAIKU_MODEL: ModelPrice(1.0, 5.0)}
    result = TriageResult(
        "silent", 0.9, "x", HAIKU_MODEL,
        usage={"input_tokens": None, "output_tokens": 4},
    )
    mc = cost_for_result(result, pricing)
    assert mc.input_tokens == 0
    assert mc.output_tokens == 4


def test_unpriced_model_costs_zero():
    mc = cost_for_result(_result("mystery-model", 1_000_000, 0), pricing={})
    assert mc.usd == 0.0


def test_email_cost_non_escalated_single_model():
    pricing = {HAIKU_MODEL: ModelPrice(1.0, 5.0)}
    verdict = _verdict([_result(HAIKU_MODEL, 1_000_000, 0)], escalated=False)
    ec = email_cost(verdict, pricing)
    assert len(ec.by_model) == 1
    assert ec.total_usd == 1.0


def test_email_cost_escalated_breaks_down_by_model():
    pricing = {HAIKU_MODEL: ModelPrice(1.0, 5.0), SONNET_MODEL: ModelPrice(2.0, 10.0)}
    verdict = _verdict(
        [_result(HAIKU_MODEL, 1_000_000, 0), _result(SONNET_MODEL, 1_000_000, 0)],
        escalated=True,
    )
    ec = email_cost(verdict, pricing)
    assert [m.model for m in ec.by_model] == [HAIKU_MODEL, SONNET_MODEL]
    assert ec.total_usd == 3.0  # $1 Haiku + $2 Sonnet, not just a combined lump
    assert ec.total_usd == sum(m.usd for m in ec.by_model)


# --- run records -------------------------------------------------------------


def test_record_run_writes_per_email_and_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("GTA_DATA_DIR", str(tmp_path))
    verdicts = [
        _verdict([_result(HAIKU_MODEL, 1_000_000, 0)], escalated=False, subject="A"),
        _verdict(
            [_result(HAIKU_MODEL, 1_000_000, 0), _result(SONNET_MODEL, 1_000_000, 0)],
            escalated=True,
            subject="B",
        ),
    ]
    record_run(verdicts)

    per_email = (tmp_path / "logs" / "costs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(per_email) == 2  # one line per email
    rec_b = json.loads(per_email[1])
    assert rec_b["subject"] == "B"
    assert rec_b["escalated"] is True
    assert len(rec_b["by_model"]) == 2  # escalation breakdown preserved

    summary_lines = (tmp_path / "logs" / "cost-summary.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(summary_lines) == 1  # one line per run
    summary = json.loads(summary_lines[0])
    assert summary["emails"] == 2
    assert summary["escalated"] == 1
    assert summary["total_usd"] == 4.0  # $1 + ($1 + $2)
    assert summary["by_model"] == {HAIKU_MODEL: 2.0, SONNET_MODEL: 2.0}
    # The run_id ties each email line back to this run's summary line.
    assert summary["run_id"] == json.loads(per_email[0])["run_id"] == json.loads(per_email[1])["run_id"]


def test_record_run_logs_no_email_content(tmp_path, monkeypatch):
    monkeypatch.setenv("GTA_DATA_DIR", str(tmp_path))
    verdict = _verdict(
        [_result(HAIKU_MODEL, 1_000_000, 0)],
        escalated=False,
        sender="Dana <dana@example.com>",
        subject="Pay up",
    )
    record_run([verdict])

    text = (tmp_path / "logs" / "costs.jsonl").read_text(encoding="utf-8")
    record = json.loads(text.strip())
    # Only sender/subject/cost/token keys — no snippet/body/reason/decision.
    assert set(record) == {"ts", "run_id", "sender", "subject", "escalated", "total_usd", "by_model"}
    assert set(record["by_model"][0]) == {"model", "input_tokens", "output_tokens", "usd"}


def test_record_run_empty_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("GTA_DATA_DIR", str(tmp_path))
    record_run([])
    assert not (tmp_path / "logs" / "costs.jsonl").exists()


def test_record_run_never_raises_on_write_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("GTA_DATA_DIR", str(tmp_path))
    # Make the log dir un-writable by planting a file where the dir must go.
    (tmp_path / "logs").write_text("not a directory", encoding="utf-8")
    verdict = _verdict([_result(HAIKU_MODEL, 1_000_000, 0)], escalated=False)
    # Should warn and return, not raise.
    record_run([verdict])
