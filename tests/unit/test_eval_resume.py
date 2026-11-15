"""Resumable evaluation rows: configuration fingerprint, resume, partial exit, quota guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent import llm
from evals.runners import harness


@pytest.fixture
def results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(harness, "RESULTS", tmp_path)
    return tmp_path


def test_rows_survive_a_restart_and_keep_order(results: Path) -> None:
    log = harness.RowLog("demo")
    log.add("b", {"v": 2})
    log.add("a", {"v": 1})
    again = harness.RowLog("demo")
    assert [r["v"] for r in again.collect(["a", "b"], harness.QuotaGuard())] == [1, 2]


def test_missing_items_exit_with_status_3(results: Path) -> None:
    log = harness.RowLog("demo")
    log.add("a", {"v": 1})
    with pytest.raises(SystemExit) as e:
        log.collect(["a", "b"], harness.QuotaGuard())
    assert e.value.code == 3


def test_rows_from_another_configuration_are_dropped(results: Path) -> None:
    harness.RowLog("demo", extra={"variant": "v0"}).add("a", {"v": 1})
    other = harness.RowLog("demo", extra={"variant": "v2"})
    assert other.get("a") is None
    lines = (results / "demo_rows.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines == []  # the stale row is removed, so the file only holds comparable rows


def test_retry_errors_reruns_failed_items(results: Path) -> None:
    harness.RowLog("demo").add("a", {"error": "TimeoutError"})
    assert harness.RowLog("demo").get("a") is not None
    assert harness.RowLog("demo", retry_errors=True).get("a") is None


def test_fingerprint_follows_prompts(results: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = harness.fingerprint()
    monkeypatch.setitem(harness.settings.config().rag, "variant", "something_else")
    assert harness.fingerprint() != before


def test_quota_guard_spoils_items_that_hit_a_daily_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = harness.QuotaGuard()
    mark = guard.mark()
    assert not guard.spoiled(mark)
    monkeypatch.setattr(llm, "_QUOTA_FAILURES", llm.quota_failures() + 1)
    assert guard.spoiled(mark) and guard.stopped


def test_other_model_failures_discard_the_item_but_keep_going(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = harness.QuotaGuard()
    mark = guard.mark()
    monkeypatch.setattr(llm, "_CALL_FAILURES", llm.call_failures() + 1)
    assert guard.spoiled(mark) and not guard.stopped and guard.discarded == 1
    assert harness.QuotaGuard().spoiled(guard.mark(), RuntimeError("Connection error."))


def test_quota_guard_recognises_a_raw_provider_cap() -> None:
    guard = harness.QuotaGuard()
    exc = RuntimeError("Rate limit reached on tokens per day (TPD). Please try again in 3m2s.")
    assert guard.spoiled(guard.mark(), exc)


def test_evaluations_run_without_fallback_models() -> None:
    assert llm.strict_models()


def test_rows_are_json_lines(results: Path) -> None:
    harness.RowLog("demo").add("a", {"v": 1})
    row = json.loads((results / "demo_rows.jsonl").read_text(encoding="utf-8"))
    assert row["key"] == "a" and len(row["fingerprint"]) == 12
