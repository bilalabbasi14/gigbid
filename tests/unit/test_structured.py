"""Structured calls: per-prompt output budgets and the retry of an answer cut off at its budget."""

from __future__ import annotations

from typing import Any

import pytest

from agent import llm, settings, structured


class Resp:
    def __init__(self, text: str, finish: str = "stop") -> None:
        self.content = text
        self.usage_metadata = {"input_tokens": 10, "output_tokens": 5}
        self.response_metadata = {"finish_reason": finish, "model_name": "m"}


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    gen = settings.config().models.generation
    monkeypatch.setitem(gen, "max_output_tokens", 1200)
    monkeypatch.setitem(gen, "max_output_tokens_by_prompt", {"analyst": 300})
    monkeypatch.setattr(structured, "load_prompt", lambda name: ("system", "user {x}"))
    return seen


def fake(seen: list[dict[str, Any]], replies: list[Resp]):  # type: ignore[no-untyped-def]
    async def ainvoke_for_node(node, msgs, *, model_kw=None, **kw):  # type: ignore[no-untyped-def]
        seen.append({"node": node, **(model_kw or {})})
        return replies.pop(0)

    return ainvoke_for_node


async def test_prompt_budget_is_sent_as_max_tokens(calls, monkeypatch) -> None:
    monkeypatch.setattr(llm, "ainvoke_for_node", fake(calls, [Resp("ok")]))
    res = await structured.call_prompt("analyst", "analyst", x=1)
    assert res.text == "ok" and calls == [{"node": "analyst", "max_tokens": 300}]


async def test_prompt_without_a_budget_uses_the_default(calls, monkeypatch) -> None:
    monkeypatch.setattr(llm, "ainvoke_for_node", fake(calls, [Resp("ok")]))
    await structured.call_prompt("critic", "critic", x=1)
    assert calls == [{"node": "critic"}]


async def test_cut_off_answer_is_retried_with_twice_the_budget(calls, monkeypatch) -> None:
    monkeypatch.setattr(llm, "ainvoke_for_node", fake(calls, [Resp("{", "length"), Resp("{}")]))
    res = await structured.call_prompt("analyst", "analyst", x=1)
    assert res.text == "{}"
    assert [c["max_tokens"] for c in calls] == [300, 600]


def test_budgets_in_config_cover_real_prompts() -> None:
    from agent.prompts import load_prompt

    for name in settings.config().models.generation.get("max_output_tokens_by_prompt", {}):
        load_prompt(name)  # a typo in config.yaml would silently disable a budget
