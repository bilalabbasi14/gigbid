from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.deps import Deps
from agent.graphs.conversation_graph import (
    build_conversation_graph,
    conversation_config,
    initial_conversation_state,
)
from agent.mcp_client import ToolProvider


class FakeLLM:
    def __init__(self, intent: str = "interview_request") -> None:
        self.intent = intent

    async def __call__(self, node: str, messages: list[Any], **kw: Any) -> AIMessage:
        text = messages[-1].content
        if "Latest client message" in text and "Free interview slots" not in text:
            return AIMessage(
                content=json.dumps(
                    {
                        "intent": self.intent,
                        "confidence": 0.9,
                        "injection_detected": False,
                        "summary": "wants a call",
                    }
                ),
                usage_metadata={"input_tokens": 50, "output_tokens": 20, "total_tokens": 70},
            )
        return AIMessage(
            content="Happy to talk. I can do Tuesday 10:00 UTC or Wednesday 14:00 UTC, 30 minutes each; which suits you? Meanwhile I will send a short plan for the first milestone.",
            usage_metadata={"input_tokens": 200, "output_tokens": 60, "total_tokens": 260},
        )


class FakeTools:
    def __init__(self, client_message: str) -> None:
        self.sent: list[dict[str, Any]] = []
        self.holds: list[dict[str, Any]] = []
        self.client_message = client_message

    def provider(self) -> ToolProvider:
        async def loader():
            async def list_messages(thread_id: str):
                return {
                    "thread_id": thread_id,
                    "items": [
                        {
                            "message_id": "m1",
                            "thread_id": thread_id,
                            "sender": "client",
                            "body": self.client_message,
                            "created_at": "2026-11-11T00:00:00Z",
                            "read": False,
                        }
                    ],
                }

            async def get_job(job_id: str):
                return {"job_id": job_id, "title": "Build a RAG chatbot"}

            async def get_free_slots(
                days: int = 5,
                slot_minutes: int = 30,
                max_slots: int = 3,
                work_start_hour: int = 9,
                work_end_hour: int = 17,
            ):
                return {
                    "slots": [
                        {"start": "2026-11-17T10:00:00", "end": "2026-11-17T10:30:00"},
                        {"start": "2026-11-18T14:00:00", "end": "2026-11-18T14:30:00"},
                    ]
                }

            async def send_message(message: dict):
                replay = any(s["idempotency_key"] == message["idempotency_key"] for s in self.sent)
                if not replay:
                    self.sent.append(message)
                return {
                    "message_id": "m2",
                    "thread_id": message["thread_id"],
                    "idempotent_replay": replay,
                }

            async def create_interview_hold(
                start: str,
                end: str,
                title: str,
                idempotency_key: str,
                with_client: str | None = None,
                thread_id: str | None = None,
            ):
                self.holds.append({"start": start, "end": end})
                return {
                    "hold_id": "hold_1",
                    "start": start,
                    "end": end,
                    "title": title,
                    "status": "tentative",
                }

            def mk(f):
                return StructuredTool.from_function(
                    coroutine=f, name=f.__name__, description=f.__name__
                )

            return {
                "marketplace": [mk(list_messages), mk(get_job), mk(send_message)],
                "workspace": [mk(get_free_slots), mk(create_interview_hold)],
                "portfolio": [],
            }

        return ToolProvider(loader=loader)


def make(tools: FakeTools, intent: str = "interview_request"):
    return build_conversation_graph(
        Deps(tools=tools.provider(), invoke=FakeLLM(intent), use_reranker=False),
        checkpointer=InMemorySaver(),
    )


async def test_interview_request_offers_slots_and_sends_after_approval():
    tools = FakeTools("Could you share a few times this week for a short call?")
    graph = make(tools)
    cfg = conversation_config("c1")
    out = await graph.ainvoke(
        initial_conversation_state(thread_id="c1", marketplace_thread_id="thr_1", job_id="job_1"),
        cfg,
    )
    assert out["status"] == "awaiting_approval" and out["intent"]["intent"] == "interview_request"
    assert len(out["proposed_slots"]) == 2 and out["pipeline_stage"] == "interview"
    assert "__interrupt__" in out and out["__interrupt__"][0].value["kind"] == "message"
    assert not tools.sent
    out = await graph.ainvoke(
        Command(resume={"action": "approve", "confirmed_slot": out["proposed_slots"][0]}), cfg
    )
    assert (
        out["status"] == "submitted"
        and len(tools.sent) == 1
        and tools.holds
        and tools.holds[0]["start"] == "2026-11-17T10:00:00"
    )


async def test_edit_with_contact_details_is_blocked():
    tools = FakeTools("What is your approach?")
    graph = make(tools, intent="question")
    cfg = conversation_config("c2")
    await graph.ainvoke(
        initial_conversation_state(thread_id="c2", marketplace_thread_id="thr_1", job_id="job_1"),
        cfg,
    )
    out = await graph.ainvoke(
        Command(
            resume={
                "action": "edit",
                "edited_cover_letter": "Sure, ping me on WhatsApp +1 415 555 0100.",
            }
        ),
        cfg,
    )
    assert out["status"] == "blocked" and not tools.sent


async def test_scam_signal_detected_by_keyword_even_if_model_misses():
    tools = FakeTools(
        "Great proposal. Let's continue on Telegram and I will pay via PayPal to skip fees."
    )
    graph = make(tools, intent="question")
    cfg = conversation_config("c3")
    out = await graph.ainvoke(
        initial_conversation_state(thread_id="c3", marketplace_thread_id="thr_1", job_id="job_1"),
        cfg,
    )
    assert out["intent"]["intent"] == "scam_signal"
    assert "__interrupt__" in out  # the human still decides; nothing auto-sent


async def test_no_new_messages_ends_quietly():
    tools = FakeTools("hello")
    graph = make(tools)
    cfg = conversation_config("c4")
    state = initial_conversation_state(
        thread_id="c4", marketplace_thread_id="thr_1", job_id="job_1"
    )
    state["messages"] = [{"message_id": "m1", "sender": "client", "body": "hello"}]
    out = await graph.ainvoke(state, cfg)
    assert out["status"] == "skipped" and "intent" not in out
