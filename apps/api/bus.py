"""Run event bus: nodes publish progress per thread; the SSE endpoint subscribes.
In-process asyncio queues by default; Redis pub/sub when a worker process runs the graphs."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

log = logging.getLogger(__name__)


class RunBus:
    def __init__(self, redis_url: str | None = None) -> None:
        self.redis_url = redis_url
        self._subs: dict[str, list[asyncio.Queue[dict[str, Any] | None]]] = {}
        self._redis = None
        self._history: dict[str, list[dict[str, Any]]] = {}

    async def _r(self):  # type: ignore[no-untyped-def]
        if self._redis is None and self.redis_url:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(self.redis_url)
                await self._redis.ping()
            except Exception as exc:  # noqa: BLE001
                log.warning("run bus: redis unavailable (%s); using in-process queues", exc)
                self.redis_url = None
                self._redis = None
        return self._redis

    async def publish(self, thread_id: str, event: dict[str, Any]) -> None:
        self._history.setdefault(thread_id, []).append(event)
        if len(self._history[thread_id]) > 500:
            self._history[thread_id] = self._history[thread_id][-500:]
        for q in list(self._subs.get(thread_id, [])):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(event)
        r = await self._r()
        if r is not None:
            with contextlib.suppress(Exception):
                await r.publish(f"run:{thread_id}", json.dumps(event, default=str))

    def history(self, thread_id: str) -> list[dict[str, Any]]:
        return list(self._history.get(thread_id, []))

    async def subscribe(self, thread_id: str) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=1000)
        self._subs.setdefault(thread_id, []).append(q)
        pubsub = None
        r = await self._r()
        task = None
        if r is not None:
            pubsub = r.pubsub()
            await pubsub.subscribe(f"run:{thread_id}")

            async def pump() -> None:
                async for msg in pubsub.listen():
                    if msg.get("type") == "message":
                        with contextlib.suppress(Exception):
                            q.put_nowait(json.loads(msg["data"]))

            task = asyncio.create_task(pump())
        try:
            while True:
                ev = await q.get()
                if ev is None:
                    break
                yield ev
                if ev.get("type") in ("done", "interrupt", "error"):
                    break
        finally:
            with contextlib.suppress(ValueError):
                self._subs[thread_id].remove(q)
            if task:
                task.cancel()
            if pubsub:
                with contextlib.suppress(Exception):
                    await pubsub.unsubscribe(f"run:{thread_id}")
                    await pubsub.aclose()


BUS: RunBus | None = None


def bus() -> RunBus:
    global BUS
    if BUS is None:
        from agent import settings

        BUS = RunBus(settings.env().redis_url if settings.env().app_env != "test" else None)
    return BUS
