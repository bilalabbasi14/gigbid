"""Dependencies injected into every node: model calls, MCP tools, config, clock. Tests pass a
fake; production uses the real providers. Nodes import nothing else that touches the network."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agent import settings
from agent.mcp_client import PROVIDER, ToolProvider
from agent.state import TraceEvent


@dataclass
class Deps:
    tools: ToolProvider = field(default_factory=lambda: PROVIDER)
    invoke: Callable[..., Awaitable[Any]] | None = None  # None -> agent.llm.ainvoke_for_node
    market_stats: dict[str, Any] | None = None
    use_reranker: bool = (
        True  # claim verification: cross-encoder support scores (off in unit tests)
    )

    @property
    def config(self):  # type: ignore[no-untyped-def]
        return settings.config()

    def stats(self) -> dict[str, Any]:
        if self.market_stats is None:
            p = settings.ROOT / "gigsim/seed/market_stats.json"
            self.market_stats = (
                json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"personas": {}}
            )
        return self.market_stats

    async def call_tool(
        self, agent: str, server: str, name: str, trace: list[TraceEvent], **args: Any
    ) -> Any:
        """Call an allowlisted MCP tool and record the call + result in the execution trace."""
        from agent.mcp_client import AGENT_TOOLS

        if name not in AGENT_TOOLS.get(agent, {}).get(server, []):
            raise PermissionError(f"agent {agent!r} is not allowed to call {server}/{name}")
        tool = await self.tools.tool(server, name)
        t0 = time.perf_counter()
        try:
            result = await tool.ainvoke(args)
        except Exception as exc:
            trace.append(
                TraceEvent(
                    ts=time.time(),
                    node=agent,
                    kind="error",
                    name=f"{server}/{name}",
                    args=args,
                    note=str(exc)[:500],
                    duration_ms=int((time.perf_counter() - t0) * 1000),
                )
            )
            raise
        trace.append(
            TraceEvent(
                ts=time.time(),
                node=agent,
                kind="tool_call",
                name=f"{server}/{name}",
                args=args,
                result=_short(result),
                duration_ms=int((time.perf_counter() - t0) * 1000),
            )
        )
        return result


def _short(x: Any, limit: int = 2000) -> Any:
    try:
        s = json.dumps(x, default=str)
    except TypeError:
        s = str(x)
    return json.loads(s) if len(s) <= limit else {"_truncated": s[:limit]}
