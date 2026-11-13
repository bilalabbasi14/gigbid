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

from agent import settings

log = logging.getLogger(__name__)


def parse_spec(spec: str) -> tuple[str, str]:
    provider, _, model = spec.partition(":")
    if not model:
        raise ValueError(f"model spec must be provider:model, got {spec!r}")
    return provider, model


@lru_cache(maxsize=1)
def groq_keys() -> tuple[str, ...]:
    """GROQ_API_KEY, then GROQ_API_KEY_2, _3, ... (environment first, then .env). Each key from a
    separate account brings its own daily and per-minute limits; the routes below rotate over the
    extra keys and use the main key last, which keeps the main key's quota for the live app."""
    from dotenv import dotenv_values

    file_vals = dotenv_values(settings.ROOT / ".env") if (settings.ROOT / ".env").exists() else {}
    main = settings.env().groq_api_key
    keys = [main.get_secret_value() if hasattr(main, "get_secret_value") else (main or "")]
    extra = sorted(
        {k for k in [*os.environ, *file_vals] if re.fullmatch(r"GROQ_API_KEY_\d+", k)},
        key=lambda k: int(k.rsplit("_", 1)[1]),
    )
    for name in extra:
        v = (os.environ.get(name) or file_vals.get(name) or "").strip().strip('"').strip("'")
        if v:
            keys.append(v)
    return tuple(dict.fromkeys(k for k in keys if k))


_CURSOR: dict[str, int] = {}


def _routes(spec: str) -> list[int]:
    """Key indices to try for a model, in order: the extra keys in rotation, the main key last."""
    n = len(groq_keys()) if spec.startswith("groq:") else 1
    if n <= 1:
        return [0]
    start = _CURSOR.get(spec, 0)
    _CURSOR[spec] = start + 1
    extra = [1 + (start + j) % (n - 1) for j in range(n - 1)]
    return [*extra, 0]


def _label(spec: str, key: int) -> str:
    return spec if key == 0 else f"{spec} (key {key + 1})"


@lru_cache(maxsize=64)
def chat_model(
    spec: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    max_retries: int = 0,
    key_index: int = 0,
) -> BaseChatModel:
    """`max_retries` is the provider client's own retry (it honours retry-after headers); keep it
    0 for calls that go through invoke_for_node, which retries and falls back itself.
    `key_index` picks one of groq_keys()."""
    env = settings.env()
    gen = settings.config().models.generation
    temperature = gen.get("temperature", 0.2) if temperature is None else temperature
    max_tokens = gen.get("max_output_tokens", 1200) if max_tokens is None else max_tokens
    timeout = gen.get("request_timeout_seconds", 60) if timeout is None else timeout
    provider, model = parse_spec(spec)

    if provider == "groq":
        from langchain_groq import ChatGroq

        extra: dict[str, Any] = {"reasoning_effort": "low"} if "gpt-oss" in model else {}
        keys = groq_keys()
        return ChatGroq(
            model=model,
            api_key=(keys[key_index] if key_index < len(keys) else None)
            or env.groq_api_key
            or None,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
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
            max_retries=max_retries,
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
            max_retries=max_retries,
        )
    raise ValueError(f"unknown provider {provider!r} in {spec!r}")


def chat_for_node(node: str, *, fallback: bool = False, **kw: Any) -> BaseChatModel:
    """A model object for callers that drive it themselves (the multi-agent baselines): the next
    key that is not at its daily cap."""
    spec = settings.config().model_for(node, fallback=fallback)
    key = next((k for k in _routes(spec) if not _capped(spec, k)), 0)
    return chat_model(spec, key_index=key, **kw)


class QuotaExhaustedError(RuntimeError):
    """Every model allowed for a call has hit its provider's daily token or request cap.

    Free tiers cap tokens per day per model (Groq: 200k), and the cap is not worth retrying for
    minutes. Callers degrade (nodes fall back to heuristics); evaluation runners stop and resume
    later instead of recording degraded rows.
    """


# spec -> monotonic time after which the model is worth trying again (daily cap reached)
_EXHAUSTED: dict[str, float] = {}
_QUOTA_FAILURES = 0
_CALL_FAILURES = 0
_RETRY_IN = re.compile(r"try again in ((?:[\d.]+(?:ms|h|m|s))+)")
_LIMIT_REQUESTED = re.compile(r"limit (\d+), (?:used \d+, )?requested (\d+)")


def quota_failures() -> int:
    """How many calls in this process failed because every allowed model was capped."""
    return _QUOTA_FAILURES


def call_failures() -> int:
    """How many calls in this process failed for any reason after every retry and fallback.
    Evaluation runners discard items that saw one: their output came from heuristic fallbacks."""
    return _CALL_FAILURES


def strict_models() -> bool:
    """GIGBID_STRICT_MODELS=1 disables fallback models, so a run measures only the configured
    model for each node (evaluation runs set this; production keeps the fallback)."""
    return os.environ.get("GIGBID_STRICT_MODELS", "0") == "1"


def _seconds(text: str) -> float | None:
    m = _RETRY_IN.search(text)
    if not m or not m.group(1):
        return None
    secs = 0.0  # Groq writes "1m2.5s", "45.2s" or "779.99ms"
    for num, unit in re.findall(r"([\d.]+)(ms|h|m|s)", m.group(1)):
        secs += float(num) * {"h": 3600, "m": 60, "s": 1, "ms": 0.001}[unit]
    return secs


def _daily_cap_wait(exc: BaseException) -> float | None:
    """Seconds until a daily-capped model can be used again, or None if this is not a daily cap."""
    text = str(exc).lower()
    if not any(k in text for k in ("per day", "(tpd)", "(rpd)")):
        return None
    secs = _seconds(text)
    return 3600.0 if secs is None else max(secs, 1.0)


def is_provider_failure(exc: BaseException) -> bool:
    """A failure of the model provider (limits, timeouts, 5xx), not of our code or the input."""
    text = str(exc).lower()
    return is_daily_cap(exc) or _is_transient(exc) or "request too large" in text


def is_daily_cap(exc: BaseException) -> bool:
    """True when the error is a provider's daily cap (or our own QuotaExhaustedError)."""
    return isinstance(exc, QuotaExhaustedError) or _daily_cap_wait(exc) is not None


def _per_minute_wait(exc: BaseException) -> float | None:
    """Seconds a provider asks us to wait for a per-minute limit (requests, tokens or output
    tokens per minute), or None if the error is not one."""
    text = str(exc).lower()
    if _daily_cap_wait(exc) is not None or "request too large" in text:
        return None
    if not any(k in text for k in ("per minute", "(tpm)", "(rpm)", "(otpm)")):
        return None
    return _seconds(text)


def _smaller_max_tokens(exc: BaseException, current: int | None) -> int | None:
    """For a request rejected as larger than a per-minute limit, a max_tokens that fits under it.
    Free tiers lower output-token limits under load (Groq: 'Request too large ... output tokens
    per minute (OTPM): Limit 1000, Requested 1200')."""
    text = str(exc).lower()
    if "request too large" not in text:
        return None
    m = _LIMIT_REQUESTED.search(text)
    if not m:
        return None
    limit, requested = int(m.group(1)), int(m.group(2))
    base = current or requested
    # the provider counts a little more than max_tokens ("Requested 1018" for 936), so shrink by
    # the overshoot as well as to the limit, whichever is smaller
    new = base - (requested - limit) - 64
    if "(otpm)" in text:
        new = min(new, limit - 64)
    return new if 128 <= new < base else None


def _is_transient(exc: BaseException) -> bool:
    if _daily_cap_wait(exc) is not None:
        return False  # a daily cap does not clear within a retry window
    text = f"{type(exc).__name__}: {exc}".lower()
    if "request too large" in text:
        return False  # waiting does not help; only a smaller request does
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


def _capkey(spec: str, key: int) -> str:
    return spec if key == 0 else f"{spec}#{key}"


def _capped(spec: str, key: int = 0) -> bool:
    until = _EXHAUSTED.get(_capkey(spec, key))
    return until is not None and time.monotonic() < until


def _note_cap(spec: str, exc: BaseException, key: int = 0) -> QuotaExhaustedError | None:
    wait = _daily_cap_wait(exc)
    if wait is None:
        return None
    _EXHAUSTED[_capkey(spec, key)] = time.monotonic() + wait
    log.warning("model %s reached its daily cap; skipping it for %.0f s", _label(spec, key), wait)
    return QuotaExhaustedError(f"{_label(spec, key)} reached its daily cap (retry in {wait:.0f} s)")


def _give_up(node: str, last: BaseException | None) -> BaseException:
    global _QUOTA_FAILURES
    if isinstance(last, QuotaExhaustedError) or last is None:
        _QUOTA_FAILURES += 1
        return last or QuotaExhaustedError(f"every model for node {node} is capped")
    return last


TRANSIENT_ATTEMPTS = 4  # timeouts, 5xx, unspecified 429s: exponential backoff
PER_MINUTE_WAIT_S = 600  # per-minute limits: keep waiting as long as the provider says, up to this


def _next_step(
    exc: BaseException, attempt: int, waited: float, kw: dict[str, Any], model: Any
) -> float | None:
    """How to retry after `exc`: seconds to wait (kw may be changed in place), or None to give up.
    `waited` is the time already spent waiting on per-minute limits for this call."""
    current = kw.get("max_tokens") or getattr(model, "max_tokens", None)
    smaller = _smaller_max_tokens(exc, current)
    if smaller is not None and attempt <= 3:
        log.info("request too large for a per-minute limit; retrying with max_tokens=%d", smaller)
        kw["max_tokens"] = smaller
        return 0.0
    wait = _per_minute_wait(exc)
    if wait is not None and waited < PER_MINUTE_WAIT_S:
        return min(65.0, wait + 0.25)
    if _is_transient(exc) and attempt < TRANSIENT_ATTEMPTS:
        return float(min(40, 2 * 2**attempt))
    return None


def _invoke(model: BaseChatModel, messages: list[BaseMessage], **kw: Any):  # type: ignore[no-untyped-def]
    attempt, waited = 0, 0.0
    while True:
        try:
            return model.invoke(messages, **kw)
        except Exception as exc:  # noqa: BLE001
            attempt += 1
            wait = _next_step(exc, attempt, waited, kw, model)
            if wait is None:
                raise
            waited += wait
            time.sleep(wait)


async def _ainvoke(model: BaseChatModel, messages: list[BaseMessage], **kw: Any):  # type: ignore[no-untyped-def]
    attempt, waited = 0, 0.0
    while True:
        try:
            return await model.ainvoke(messages, **kw)
        except Exception as exc:  # noqa: BLE001
            attempt += 1
            wait = _next_step(exc, attempt, waited, kw, model)
            if wait is None:
                raise
            waited += wait
            await asyncio.sleep(wait)


_SLOTS: dict[tuple[int, str, int], asyncio.Semaphore] = {}


def _slot(spec: str, key: int = 0) -> asyncio.Semaphore:
    """At most budgets.max_concurrent_calls_per_model calls in flight per model and event loop:
    free tiers cap tokens per minute per model, and a burst of parallel calls only buys 429s."""
    slot = (id(asyncio.get_running_loop()), spec, key)  # limits are per key, so slots are too
    if slot not in _SLOTS:
        cap = settings.config().budgets.get("max_concurrent_calls_per_model", 2)
        n = cap.get(spec, cap.get("default", 2)) if isinstance(cap, dict) else cap
        _SLOTS[slot] = asyncio.Semaphore(max(1, int(n)))
    return _SLOTS[slot]


def _brief(exc: BaseException) -> str:
    """The provider's message, short and without account ids, for the log."""
    text = re.sub(r"org_[A-Za-z0-9]+", "org_…", str(exc))
    return " ".join(text.split())[:240]


def _failed() -> None:
    global _CALL_FAILURES
    _CALL_FAILURES += 1


def invoke_for_node(
    node: str, messages: list[BaseMessage], *, model_kw: dict[str, Any] | None = None, **kw: Any
):  # type: ignore[no-untyped-def]
    """Invoke the node's configured model; on persistent transient failure or a daily cap use its
    fallback (unless strict). `model_kw` (temperature, max_tokens, timeout) overrides the config
    defaults for this call."""
    model_kw = model_kw or {}
    last: BaseException | None = None
    for spec in _candidates(node):
        for key in _routes(spec):
            if _capped(spec, key):
                last = QuotaExhaustedError(f"{_label(spec, key)} is still at its daily cap")
                continue
            try:
                return _invoke(chat_model(spec, key_index=key, **model_kw), messages, **kw)
            except Exception as exc:  # noqa: BLE001
                capped = _note_cap(spec, exc, key)
                if capped is None and not _is_transient(exc):
                    _failed()
                    raise
                last = capped or exc
                log.warning(
                    "node %s: model %s failed (%s: %s)",
                    node,
                    _label(spec, key),
                    type(exc).__name__,
                    _brief(exc),
                )
    _failed()
    raise _give_up(node, last)


async def ainvoke_for_node(
    node: str, messages: list[BaseMessage], *, model_kw: dict[str, Any] | None = None, **kw: Any
):  # type: ignore[no-untyped-def]
    model_kw = model_kw or {}
    last: BaseException | None = None
    for spec in _candidates(node):
        for key in _routes(spec):
            if _capped(spec, key):
                last = QuotaExhaustedError(f"{_label(spec, key)} is still at its daily cap")
                continue
            try:
                async with _slot(spec, key):
                    return await _ainvoke(
                        chat_model(spec, key_index=key, **model_kw), messages, **kw
                    )
            except Exception as exc:  # noqa: BLE001
                capped = _note_cap(spec, exc, key)
                if capped is None and not _is_transient(exc):
                    _failed()
                    raise
                last = capped or exc
                log.warning(
                    "node %s: model %s failed (%s: %s)",
                    node,
                    _label(spec, key),
                    type(exc).__name__,
                    _brief(exc),
                )
    _failed()
    raise _give_up(node, last)
