"""SSE bridge from LangGraph streams to the browser. The run viewer and the studio subscribe to
/runs/{thread_id}/stream; a page refresh replays the buffered history first, so no progress is
lost, and the stream closes on done / interrupt / error."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from apps.api.auth.security import CurrentUser
from apps.api.bus import bus
from apps.api.db import Run, get_session

router = APIRouter(prefix="/runs", tags=["runs"])


async def _events(thread_id: str, request: Request, status: str) -> AsyncIterator[dict[str, Any]]:
    b = bus()
    yield {
        "event": "snapshot",
        "data": json.dumps(
            {"type": "snapshot", "status": status, "history": b.history(thread_id)[-100:]},
            default=str,
        ),
    }
    if status in (
        "submitted",
        "skipped",
        "watch",
        "rejected",
        "blocked",
        "needs_attention",
        "failed",
    ):
        yield {"event": "done", "data": json.dumps({"type": "done", "status": status})}
        return
    if status == "awaiting_approval":
        yield {"event": "interrupt", "data": json.dumps({"type": "interrupt", "status": status})}
        return
    async for ev in b.subscribe(thread_id):
        if await request.is_disconnected():
            break
        yield {"event": ev.get("type", "message"), "data": json.dumps(ev, default=str)}


@router.get("/{thread_id}/stream")
async def stream_run(thread_id: str, request: Request, user: CurrentUser):
    async for s in get_session():
        run = await s.get(Run, thread_id)
    if run is None or run.user_id != user.user_id:
        raise HTTPException(404, "run not found")
    return EventSourceResponse(_events(thread_id, request, run.status), ping=15)


async def _heartbeat() -> None:  # pragma: no cover
    await asyncio.sleep(0)
