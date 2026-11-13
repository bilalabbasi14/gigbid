"""Model layer: daily caps, per-minute limits, oversize requests, fallback order, strict mode and
failure accounting."""

from __future__ import annotations

from typing import Any

import pytest

from agent import llm

TPD = (
    "Error code: 429 - Rate limit reached for model `openai/gpt-oss-20b` on tokens per day (TPD): "
    "Limit 200000, Used 198343, Requested 2354. Please try again in 5m1.104s."
)
TPM = "Error code: 429 - Rate limit reached on tokens per minute (TPM). Please try again in 1.2s."
OTPM_WAIT = (
    "Error code: 429 - Rate limit reached for model `qwen/qwen3.8-27b` on output tokens per minute "
    "(OTPM): Limit 1000, Used 835, Requested 990. Please try again in 49.5s."
)
OTPM_TOO_LARGE = (
    "Error code: 429 - Request too large for model `qwen/qwen3.8-27b` on output tokens per minute "
    "(OTPM): Limit 1000, Requested 1200. The request's expected output tokens exceed the enforced "
    "limit; reduce max_tokens (or the request's expected output) and try again."
)


class FakeModel:
    max_tokens = 1200

    def __init__(self, spec: str, script: dict[str, list[Any]]) -> None:
        self.spec, self.script = spec, script

    async def ainvoke(self, messages: Any, **kw: Any) -> str:
        CALLS.append({"spec": self.spec, **kw})
        step = self.script[self.spec].pop(0)
        if isinstance(step, Exception):
            raise step
        return step


CALLS: list[dict[str, Any]] = []
SLEEPS: list[float] = []


@pytest.fixture
def models(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    script: dict[str, list[Any]] = {}
    CALLS.clear()
    SLEEPS.clear()

    async def fake_sleep(secs: float) -> None:
        SLEEPS.append(secs)

    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(llm, "_CALL_FAILURES", 0)
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


def test_per_minute_limits_wait_as_long_as_the_provider_says() -> None:
    assert llm._per_minute_wait(RuntimeError(OTPM_WAIT)) == pytest.approx(49.5)
    assert llm._per_minute_wait(RuntimeError(TPM)) == pytest.approx(1.2)
    assert llm._per_minute_wait(RuntimeError(TPD)) is None
    assert llm._per_minute_wait(RuntimeError(OTPM_TOO_LARGE)) is None


async def test_output_limit_wait_is_honoured(models: dict[str, list[Any]]) -> None:
    models["test:primary"] = [RuntimeError(OTPM_WAIT), "ok"]
    assert await llm.ainvoke_for_node("verifier", []) == "ok"
    assert SLEEPS == [49.75]


async def test_oversize_request_is_retried_smaller_not_waited_on(
    models: dict[str, list[Any]],
) -> None:
    models["test:primary"] = [RuntimeError(OTPM_TOO_LARGE), "ok"]
    assert await llm.ainvoke_for_node("verifier", []) == "ok"
    assert [c.get("max_tokens") for c in CALLS] == [None, 936]
    assert SLEEPS == [0.0]
    assert not llm._is_transient(RuntimeError(OTPM_TOO_LARGE))


async def test_every_failed_call_is_counted(models: dict[str, list[Any]], monkeypatch) -> None:
    monkeypatch.setenv("GIGBID_STRICT_MODELS", "1")
    models["test:primary"] = [RuntimeError("503 overloaded")] * 4
    with pytest.raises(RuntimeError):
        await llm.ainvoke_for_node("analyst", [])
    assert llm.call_failures() == 1 and llm.quota_failures() == 0
    assert llm.is_provider_failure(RuntimeError("503 overloaded"))
    assert not llm.is_provider_failure(ValueError("missing field"))


async def test_calls_per_model_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    monkeypatch.setitem(llm.settings.config().budgets, "max_concurrent_calls_per_model", 2)
    monkeypatch.setattr(llm, "_SLOTS", {})
    monkeypatch.setattr(
        type(llm.settings.config()), "model_for", lambda self, node, fallback=False: "test:m"
    )
    live, peak = 0, 0

    class Slow:
        async def ainvoke(self, messages: Any, **kw: Any) -> str:
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            loop = asyncio.get_running_loop()
            done = loop.create_future()
            loop.call_later(0.01, done.set_result, None)
            await done
            live -= 1
            return "ok"

    monkeypatch.setattr(llm, "chat_model", lambda spec, **kw: Slow())
    await asyncio.gather(*(llm.ainvoke_for_node("analyst", []) for _ in range(6)))
    assert peak == 2


def test_failure_log_hides_account_ids() -> None:
    msg = llm._brief(RuntimeError("Rate limit for org_01kym7na02e2sbmg99cs7242ey on TPM"))
    assert "org_01" not in msg and "TPM" in msg


def test_waits_in_milliseconds_are_understood() -> None:
    otpm = (
        "Rate limit reached for model `qwen/qwen3.8-27b` on output tokens per minute (OTPM): "
        "Limit 1000, Used 313, Requested 700. Please try again in 779.99999ms."
    )
    assert llm._per_minute_wait(RuntimeError(otpm)) == pytest.approx(0.78, abs=0.01)
