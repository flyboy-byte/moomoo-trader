"""Weekly synthesis API-call tests.

Regression tests for a bug found 2026-08-29 by the API cost audit (/claude-api
cost-optimize). synthesize_week() ran with max_tokens=512 against a six-field JSON
schema. Every single run since deployment — W30, W31, W32, W33, W34, five for five —
was truncated mid-string, raised "Unterminated string" out of json.loads(), and was
swallowed by the fail-open except branch. Discord got "No summary available." each
Monday and nothing recorded why.

Three things let a 100%-failure rate survive five weeks undetected:
  1. max_tokens was treated as a tuning knob rather than a backstop.
  2. stop_reason was never checked, so a truncated response was parsed as if complete
     and surfaced as a confusing JSON error rather than "the response was cut off".
  3. The except branch skipped _append_api_usage entirely, so failed-but-billed calls
     left no trace in api_usage.jsonl — the audit found zero weekly_synthesis records
     there despite five weeks of cron runs.

This module covers all three, plus the model-attribution field.
"""
import json
from unittest.mock import MagicMock

import pytest

from mm import morning_regime


def _fake_message(text: str, *, stop_reason: str = "end_turn",
                  in_tok: int = 400, out_tok: int = 600) -> MagicMock:
    block = MagicMock()
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    msg.stop_reason = stop_reason
    msg.usage.input_tokens = in_tok
    msg.usage.output_tokens = out_tok
    return msg


GOOD_JSON = json.dumps({
    "summary": "Three strategies traded, none decisively.",
    "bright_spots": ["vwap_pb held up"],
    "concerns": ["sample too small"],
    "regime_verdict": "labels roughly matched outcomes",
    "recommendation": "more data needed",
    "data_quality": "n=12, far below any gate",
})


@pytest.fixture
def synth_env(tmp_path, monkeypatch):
    """Point synthesize_week at an empty tmp logs dir with an API key set."""
    import mm.config as _config
    monkeypatch.setattr(_config.cfg, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(_config.cfg, "anthropic_model_cheap", "claude-haiku-4-5-20251001")
    return tmp_path


def _run(monkeypatch, logs_dir, message):
    """Run synthesize_week with a mocked Anthropic client returning `message`."""
    import anthropic
    client = MagicMock()
    client.messages.create.return_value = message
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: client)
    result = morning_regime.synthesize_week(week_str="2026-W35", logs_dir=logs_dir)
    return result, client


def _usage_records(logs_dir):
    path = logs_dir / "api_usage.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# The truncation bug itself
# ---------------------------------------------------------------------------

def test_max_tokens_has_headroom_over_the_schema():
    """Regression: 512 was not enough for the six-field response and truncated it
    every week. The response wants ~600 output tokens; the backstop must clear that
    with real margin, not sit on the cliff edge."""
    assert morning_regime.SYNTHESIS_MAX_TOKENS >= 2048, (
        "max_tokens is a backstop, not a knob — 512 truncated W30-W34 mid-string."
    )


def test_call_uses_the_module_constant_not_a_literal(synth_env, monkeypatch):
    _, client = _run(monkeypatch, synth_env, _fake_message(GOOD_JSON))
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["max_tokens"] == morning_regime.SYNTHESIS_MAX_TOKENS


def test_truncated_response_is_reported_as_truncation_not_a_json_error(
    synth_env, monkeypatch
):
    """The five real failures surfaced as 'Unterminated string starting at line 14',
    which reads like a model formatting problem and sent the diagnosis in the wrong
    direction. A max_tokens stop must say so in plain words."""
    truncated = GOOD_JSON[:120]  # cut mid-string, exactly like the real failures
    result, _ = _run(monkeypatch, synth_env,
                     _fake_message(truncated, stop_reason="max_tokens"))
    err = result["analysis"]["error"]
    assert "truncated" in err
    assert "max_tokens" in err
    assert result["analysis"]["stop_reason"] == "max_tokens"


def test_failure_preserves_the_raw_response_for_diagnosis(synth_env, monkeypatch):
    """The old except branch kept only str(e). Five weeks of failures left no way to
    see what the model actually returned."""
    truncated = GOOD_JSON[:120]
    result, _ = _run(monkeypatch, synth_env,
                     _fake_message(truncated, stop_reason="max_tokens"))
    assert result["analysis"]["raw_response"] == truncated


# ---------------------------------------------------------------------------
# Usage logging — failed calls still cost money
# ---------------------------------------------------------------------------

def test_usage_is_logged_on_success(synth_env, monkeypatch):
    _run(monkeypatch, synth_env, _fake_message(GOOD_JSON))
    recs = _usage_records(synth_env)
    assert len(recs) == 1
    assert recs[0]["call_type"] == "weekly_synthesis"
    assert recs[0]["parsed_ok"] is True


def test_usage_is_logged_even_when_parsing_fails(synth_env, monkeypatch):
    """Regression: the old except branch returned before _append_api_usage, so a
    billed-but-failed call was invisible. api_usage.jsonl held zero weekly_synthesis
    records after five weeks of cron runs — that silence read as 'never ran'."""
    _run(monkeypatch, synth_env,
         _fake_message(GOOD_JSON[:120], stop_reason="max_tokens"))
    recs = _usage_records(synth_env)
    assert len(recs) == 1, "a failed call still burned tokens and must be logged"
    assert recs[0]["parsed_ok"] is False
    assert recs[0]["stop_reason"] == "max_tokens"
    assert recs[0]["output_tokens"] == 600


def test_usage_record_names_the_model(synth_env, monkeypatch):
    """Cost cannot be attributed without it — 163 of 185 records in the real
    api_usage.jsonl have no model field, so the 2026-08-25 Sonnet->Haiku split was
    unverifiable from the project's own logs."""
    _run(monkeypatch, synth_env, _fake_message(GOOD_JSON))
    assert _usage_records(synth_env)[0]["model"] == "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# Fail-open behaviour must survive the fix
# ---------------------------------------------------------------------------

def test_still_fails_open_and_writes_stats_on_api_error(synth_env, monkeypatch):
    import anthropic
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("connection reset")
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: client)
    result = morning_regime.synthesize_week(week_str="2026-W35", logs_dir=synth_env)
    assert "error" in result["analysis"]
    assert "stats" in result
    assert (synth_env / "synthesis_2026-W35.json").exists()


def test_no_usage_logged_when_the_call_never_reached_the_api(synth_env, monkeypatch):
    """A connection error bills nothing — don't write a zero-token usage record."""
    import anthropic
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("connection reset")
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: client)
    morning_regime.synthesize_week(week_str="2026-W35", logs_dir=synth_env)
    assert _usage_records(synth_env) == []


def test_markdown_fenced_json_still_parses(synth_env, monkeypatch):
    fenced = f"```json\n{GOOD_JSON}\n```"
    result, _ = _run(monkeypatch, synth_env, _fake_message(fenced))
    assert result["analysis"]["recommendation"] == "more data needed"


# ---------------------------------------------------------------------------
# The other hardcoded-model site the audit found
# ---------------------------------------------------------------------------

def test_analyst_uses_configured_cheap_model_not_a_hardcoded_id(monkeypatch):
    """mm/analyst.py pinned "claude-haiku-4-5-20251001" in a module constant, opting
    itself out of the ANTHROPIC_MODEL_CHEAP split added 2026-08-25."""
    import anthropic
    import mm.config as _config
    from mm import analyst

    monkeypatch.setattr(_config.cfg, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(_config.cfg, "anthropic_model_cheap", "sentinel-model")
    client = MagicMock()
    client.messages.create.return_value = _fake_message("looks fine")
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: client)

    analyst.haiku_interpret("PF 1.02\n")
    assert client.messages.create.call_args.kwargs["model"] == "sentinel-model"
