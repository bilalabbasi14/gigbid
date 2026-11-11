"""Model layer: daily-cap detection, fallback order, strict mode, quota-failure accounting."""

from __future__ import annotations

from typing import Any

import pytest

from agent import llm

TPD = (
    "Error code: 429 - Rate limit reached for model `openai/gpt-oss-20b` on tokens per day (TPD): "
    "Limit 200000, Used 198343, Requested 2354. Please try again in 5m1.104s."
)
TPM = "Error code: 429 - Rate limit reached on tokens per minute (TPM). Please try again in 1.2s."


class FakeModel:
    def __init__(self, spec: str, script: dict[str, list[Any]]) -> None:
        self.spec, self.script = spec, script

    async def ainvoke(self, messages: Any, **kw: Any) -> str:
        step = self.script[self.spec].pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
def models(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    script: dict[str, list[Any]] = {}
    specs = {False: "test:primary", True: "test:fallback"}
    monkeypatch.setattr(llm, "_EXHAUSTED", {})
    monkeypatch.setattr(llm, "_QUOTA_FAILURES", 0)
    monkeypatch.setattr(
        type(llm.settings.config()), "model_for", lambda self, node, fallback=False: specs[fallback]
    )
    monkeypatch.setattr(llm, "chat_model", lambda spec, **kw: FakeModel(spec, script))
    monkeypatch.delenv("GIGBID_STRICT_MODELS", raising=False)
    return script


def test_daily_cap_wait_parses_groq_message() -> None:
    assert llm._daily_cap_wait(RuntimeError(TPD)) == pytest.approx(301.104)
    assert llm._daily_cap_wait(RuntimeError(TPM)) is None
    assert llm._daily_cap_wait(RuntimeError("requests per day (RPD)")) == 3600.0


def test_daily_cap_is_not_retried_as_transient() -> None:
    assert not llm._is_transient(RuntimeError(TPD))
    assert llm._is_transient(RuntimeError(TPM))


async def test_daily_cap_goes_straight_to_fallback_and_is_remembered(
    models: dict[str, list[Any]],
) -> None:
    models["test:primary"] = [RuntimeError(TPD)]
    models["test:fallback"] = ["first", "second"]
    assert await llm.ainvoke_for_node("analyst", []) == "first"
    # the capped primary is skipped on the next call instead of spending a request
    assert await llm.ainvoke_for_node("analyst", []) == "second"
    assert llm.quota_failures() == 0


async def test_strict_mode_raises_instead_of_falling_back(
    models: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIGBID_STRICT_MODELS", "1")
    models["test:primary"] = [RuntimeError(TPD)]
    models["test:fallback"] = ["never used"]
    with pytest.raises(llm.QuotaExhaustedError):
        await llm.ainvoke_for_node("analyst", [])
    assert llm.quota_failures() == 1
    assert models["test:fallback"] == ["never used"]


async def test_both_capped_counts_one_quota_failure(models: dict[str, list[Any]]) -> None:
    models["test:primary"] = [RuntimeError(TPD)]
    models["test:fallback"] = [RuntimeError(TPD)]
    with pytest.raises(llm.QuotaExhaustedError):
        await llm.ainvoke_for_node("writer", [])
    assert llm.quota_failures() == 1


async def test_non_transient_error_is_raised_unchanged(models: dict[str, list[Any]]) -> None:
    models["test:primary"] = [ValueError("bad request: unknown field")]
    with pytest.raises(ValueError):
        await llm.ainvoke_for_node("critic", [])
    assert llm.quota_failures() == 0
