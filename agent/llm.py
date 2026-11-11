"""Chat-model factory. The only place that knows about providers.

Model specs are provider-qualified strings from agent/config.yaml, e.g. `groq:llama-3.1-8b-instant`,
`openrouter:qwen/qwen3-235b-a22b:free`, `ollama:qwen3:4b-instruct`, `openai:gpt-4.1-mini`.
Nodes call `chat_for_node("writer")` and never name a provider or model.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from functools import lru_cache
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from agent import settings

log = logging.getLogger(__name__)


def parse_spec(spec: str) -> tuple[str, str]:
    provider, _, model = spec.partition(":")
    if not model:
        raise ValueError(f"model spec must be provider:model, got {spec!r}")
    return provider, model


@lru_cache(maxsize=32)
def chat_model(
    spec: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> BaseChatModel:
    env = settings.env()
    gen = settings.config().models.generation
    temperature = gen.get("temperature", 0.2) if temperature is None else temperature
    max_tokens = gen.get("max_output_tokens", 1200) if max_tokens is None else max_tokens
    timeout = gen.get("request_timeout_seconds", 60) if timeout is None else timeout
    provider, model = parse_spec(spec)

    if provider == "groq":
        from langchain_groq import ChatGroq

        extra: dict[str, Any] = {"reasoning_effort": "low"} if "gpt-oss" in model else {}
        return ChatGroq(
            model=model,
            api_key=env.groq_api_key or None,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=0,
            **extra,
        )
    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=env.openrouter_api_key or "missing",
            base_url="https://openrouter.ai/api/v1",
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=0,
        )
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model,
            base_url=env.ollama_base_url,
            temperature=temperature,
            num_predict=max_tokens,
            num_ctx=int(gen.get("local_context_tokens", 6144)),
            reasoning=False,  # qwen3 thinks by default: slow on CPU and noise around the JSON
        )
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=env.openai_api_key or "missing",
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=0,
        )
    raise ValueError(f"unknown provider {provider!r} in {spec!r}")


def chat_for_node(node: str, *, fallback: bool = False, **kw: Any) -> BaseChatModel:
    return chat_model(settings.config().model_for(node, fallback=fallback), **kw)


class QuotaExhaustedError(RuntimeError):
    """Every model allowed for a call has hit its provider's daily token or request cap.

    Free tiers cap tokens per day per model (Groq: 200k), and the cap is not worth retrying for
    minutes. Callers degrade (nodes fall back to heuristics); evaluation runners stop and resume
    later instead of recording degraded rows.
    """


# spec -> monotonic time after which the model is worth trying again (daily cap reached)
_EXHAUSTED: dict[str, float] = {}
_QUOTA_FAILURES = 0


def quota_failures() -> int:
    """How many calls in this process failed because every allowed model was capped."""
    return _QUOTA_FAILURES


def strict_models() -> bool:
    """GIGBID_STRICT_MODELS=1 disables fallback models, so a run measures only the configured
    model for each node (evaluation runs set this; production keeps the fallback)."""
    return os.environ.get("GIGBID_STRICT_MODELS", "0") == "1"


def _daily_cap_wait(exc: BaseException) -> float | None:
    """Seconds until a daily-capped model can be used again, or None if this is not a daily cap."""
    text = str(exc).lower()
    if not any(k in text for k in ("per day", "(tpd)", "(rpd)")):
        return None
    m = re.search(r"try again in ((?:\d+h)?(?:\d+m)?(?:[\d.]+s)?)", text)
    if not m or not m.group(1):
        return 3600.0
    secs = 0.0
    for num, unit in re.findall(r"([\d.]+)([hms])", m.group(1)):
        secs += float(num) * {"h": 3600, "m": 60, "s": 1}[unit]
    return max(secs, 1.0)


def is_daily_cap(exc: BaseException) -> bool:
    """True when the error is a provider's daily cap (or our own QuotaExhaustedError)."""
    return isinstance(exc, QuotaExhaustedError) or _daily_cap_wait(exc) is not None


def _is_transient(exc: BaseException) -> bool:
    if _daily_cap_wait(exc) is not None:
        return False  # a daily cap does not clear within a retry window
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        k in text
        for k in (
            "429",
            "rate limit",
            "rate_limit",
            "timeout",
            "timed out",
            "503",
            "502",
            "500",
            "overloaded",
            "connection",
            "temporarily",
        )
    )


def _candidates(node: str) -> list[str]:
    cfg = settings.config()
    specs = [cfg.model_for(node)]
    if not strict_models():
        specs.append(cfg.model_for(node, fallback=True))
    return list(dict.fromkeys(specs))


def _capped(spec: str) -> bool:
    until = _EXHAUSTED.get(spec)
    return until is not None and time.monotonic() < until


def _note_cap(spec: str, exc: BaseException) -> QuotaExhaustedError | None:
    wait = _daily_cap_wait(exc)
    if wait is None:
        return None
    _EXHAUSTED[spec] = time.monotonic() + wait
    log.warning("model %s reached its daily cap; skipping it for %.0f s", spec, wait)
    return QuotaExhaustedError(f"{spec} reached its daily cap (retry in {wait:.0f} s)")


def _give_up(node: str, last: BaseException | None) -> BaseException:
    global _QUOTA_FAILURES
    if isinstance(last, QuotaExhaustedError) or last is None:
        _QUOTA_FAILURES += 1
        return last or QuotaExhaustedError(f"every model for node {node} is capped")
    return last


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=2, max=40),
    retry=retry_if_exception(_is_transient),
    reraise=True,
)
def _invoke(model: BaseChatModel, messages: list[BaseMessage], **kw: Any):  # type: ignore[no-untyped-def]
    return model.invoke(messages, **kw)


def invoke_for_node(
    node: str, messages: list[BaseMessage], *, model_kw: dict[str, Any] | None = None, **kw: Any
):  # type: ignore[no-untyped-def]
    """Invoke the node's configured model; on persistent transient failure or a daily cap use its
    fallback (unless strict). `model_kw` (temperature, max_tokens, timeout) overrides the config
    defaults for this call."""
    model_kw = model_kw or {}
    last: BaseException | None = None
    for spec in _candidates(node):
        if _capped(spec):
            last = QuotaExhaustedError(f"{spec} is still at its daily cap")
            continue
        try:
            return _invoke(chat_model(spec, **model_kw), messages, **kw)
        except Exception as exc:  # noqa: BLE001
            capped = _note_cap(spec, exc)
            if capped is None and not _is_transient(exc):
                raise
            last = capped or exc
            log.warning("node %s: model %s failed (%s)", node, spec, type(exc).__name__)
    raise _give_up(node, last)


async def _ainvoke(model: BaseChatModel, messages: list[BaseMessage], **kw: Any):  # type: ignore[no-untyped-def]
    attempt = 0
    while True:
        try:
            return await model.ainvoke(messages, **kw)
        except Exception as exc:  # noqa: BLE001
            attempt += 1
            if not _is_transient(exc) or attempt >= 4:
                raise
            await asyncio.sleep(min(40, 2 * 2**attempt))


async def ainvoke_for_node(
    node: str, messages: list[BaseMessage], *, model_kw: dict[str, Any] | None = None, **kw: Any
):  # type: ignore[no-untyped-def]
    model_kw = model_kw or {}
    last: BaseException | None = None
    for spec in _candidates(node):
        if _capped(spec):
            last = QuotaExhaustedError(f"{spec} is still at its daily cap")
            continue
        try:
            return await _ainvoke(chat_model(spec, **model_kw), messages, **kw)
        except Exception as exc:  # noqa: BLE001
            capped = _note_cap(spec, exc)
            if capped is None and not _is_transient(exc):
                raise
            last = capped or exc
            log.warning("node %s: model %s failed (%s)", node, spec, type(exc).__name__)
    raise _give_up(node, last)
