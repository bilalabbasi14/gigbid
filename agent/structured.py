"""Structured LLM calls: prompt file -> Pydantic model, provider-agnostic, with one repair pass."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from agent import llm
from agent.guardrails import SYSTEM_GUARD
from agent.prompts import load_prompt


def _extract_json(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    m = re.search(r"[\[{]", text)
    if m:
        text = text[m.start() :]
    # trim trailing prose after the last closing bracket
    last = max(text.rfind("}"), text.rfind("]"))
    if last > 0:
        text = text[: last + 1]
    return json.loads(text)


def _content(resp: Any) -> str:
    c = resp.content
    if isinstance(c, str):
        return c
    return "".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in c)


def usage_of(resp: Any) -> dict[str, int]:
    u = getattr(resp, "usage_metadata", None) or {}
    return {
        "input_tokens": int(u.get("input_tokens", 0)),
        "output_tokens": int(u.get("output_tokens", 0)),
    }


class LLMResult:
    def __init__(self, text: str, usage: dict[str, int], duration_ms: int, model: str) -> None:
        self.text, self.usage, self.duration_ms, self.model = text, usage, duration_ms, model


async def call_prompt(
    node: str, prompt_name: str, *, system_extra: str = "", invoke=None, **fields: Any
) -> LLMResult:
    """Fill the named prompt and call the node's model. `invoke` can be swapped in tests."""
    system, user = load_prompt(prompt_name)
    system = f"{system}\n\n{SYSTEM_GUARD}" + (f"\n\n{system_extra}" if system_extra else "")
    msgs: list[BaseMessage] = [
        SystemMessage(content=system),
        HumanMessage(content=user.format(**fields)),
    ]
    t0 = time.perf_counter()
    resp = await (invoke or llm.ainvoke_for_node)(node, msgs)
    return LLMResult(
        _content(resp),
        usage_of(resp),
        int((time.perf_counter() - t0) * 1000),
        getattr(resp, "response_metadata", {}).get("model_name", ""),
    )


async def call_structured[T: BaseModel](
    node: str, prompt_name: str, model: type[T], *, invoke=None, **fields: Any
) -> tuple[T, LLMResult]:
    schema_hint = f"Respond with ONLY a JSON object matching this schema (no prose, no markdown fences):\n{json.dumps(model.model_json_schema(), ensure_ascii=False)}"
    result = await call_prompt(node, prompt_name, system_extra=schema_hint, invoke=invoke, **fields)
    try:
        return model.model_validate(_extract_json(result.text)), result
    except (ValueError, ValidationError) as exc:
        # one repair pass: show the error and ask for corrected JSON
        system, _ = load_prompt(prompt_name)
        msgs: list[BaseMessage] = [
            SystemMessage(content=f"{system}\n\n{SYSTEM_GUARD}\n\n{schema_hint}"),
            HumanMessage(
                content=f"Your previous output could not be parsed:\n{result.text[:3000]}\n\nError: {exc}\n\nReturn the corrected JSON object only."
            ),
        ]
        t0 = time.perf_counter()
        resp = await (invoke or llm.ainvoke_for_node)(node, msgs)
        fixed = LLMResult(
            _content(resp), usage_of(resp), int((time.perf_counter() - t0) * 1000), result.model
        )
        fixed.usage = {
            k: fixed.usage.get(k, 0) + result.usage.get(k, 0)
            for k in ("input_tokens", "output_tokens")
        }
        return model.model_validate(_extract_json(fixed.text)), fixed
