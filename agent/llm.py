"""Chat-model factory. The only place that knows about providers.

Model specs are provider-qualified strings from agent/config.yaml, e.g. `groq:llama-3.1-8b-instant`,
`openrouter:qwen/qwen3-235b-a22b:free`, `ollama:qwen3:4b`, `openai:gpt-4.1-mini`.
Nodes call `chat_for_node("writer")` and never name a provider or model.
"""

from __future__ import annotations

import logging
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


def _is_transient(exc: BaseException) -> bool:
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
    """Invoke the node's configured model; on persistent transient failure use its fallback.

    `model_kw` (temperature, max_tokens, timeout) overrides the config defaults for this call.
    """
    model_kw = model_kw or {}
    try:
        return _invoke(chat_for_node(node, **model_kw), messages, **kw)
    except Exception as exc:  # noqa: BLE001
        if not _is_transient(exc):
            raise
        log.warning("node %s: primary model failed (%s); using fallback", node, type(exc).__name__)
        return _invoke(chat_for_node(node, fallback=True, **model_kw), messages, **kw)


async def _ainvoke(model: BaseChatModel, messages: list[BaseMessage], **kw: Any):  # type: ignore[no-untyped-def]
    attempt = 0
    while True:
        try:
            return await model.ainvoke(messages, **kw)
        except Exception as exc:  # noqa: BLE001
            attempt += 1
            if not _is_transient(exc) or attempt >= 4:
                raise
            import asyncio

            await asyncio.sleep(min(40, 2 * 2**attempt))


async def ainvoke_for_node(
    node: str, messages: list[BaseMessage], *, model_kw: dict[str, Any] | None = None, **kw: Any
):  # type: ignore[no-untyped-def]
    model_kw = model_kw or {}
    try:
        return await _ainvoke(chat_for_node(node, **model_kw), messages, **kw)
    except Exception as exc:  # noqa: BLE001
        if not _is_transient(exc):
            raise
        log.warning("node %s: primary model failed (%s); using fallback", node, type(exc).__name__)
        return await _ainvoke(chat_for_node(node, fallback=True, **model_kw), messages, **kw)
