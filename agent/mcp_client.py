"""MCP client discipline (A6): one MultiServerMCPClient, per-agent tool allowlists, timeouts,
bounded retries and a degraded-mode signal.

Agents never import adapters or HTTP clients; they receive LangChain tools from `tools_for()`.
In tests and single-process runs the servers are mounted in-memory (`InProcessRegistry`), so the
exact same allowlists apply without network.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from agent import settings

log = logging.getLogger(__name__)

# Which tools each agent may call. Names are MCP tool names; servers are ours plus third-party.
AGENT_TOOLS: dict[str, dict[str, list[str]]] = {
    "scout": {"marketplace": ["search_jobs", "get_job", "marketplace_health"]},
    "analyst": {},
    "risk_assessor": {"marketplace": ["get_client_history", "get_job"]},
    "fit_matcher": {"portfolio": ["search_evidence", "get_case_study", "list_skills"]},
    "pricing": {
        "marketplace": ["get_client_history", "get_connects_balance", "marketplace_health"]
    },
    "writer": {"portfolio": ["search_evidence", "get_case_study"]},
    "verifier": {"portfolio": ["search_evidence", "get_case_study"]},
    "critic": {"portfolio": ["search_evidence", "get_case_study"]},
    "compliance": {},
    "client_liaison": {
        "marketplace": ["list_threads", "list_messages", "send_message", "get_job"],
        "workspace": ["get_free_slots", "create_interview_hold", "create_email_draft"],
    },
    "submitter": {
        "marketplace": ["create_proposal_draft", "submit_proposal", "get_connects_balance"]
    },
    "portfolio_builder": {
        "github": ["search_repositories", "get_file_contents", "list_commits", "get_repository"],
        "portfolio": ["list_skills"],
    },
    "single_agent": {
        "marketplace": [
            "search_jobs",
            "get_job",
            "get_client_history",
            "get_connects_balance",
            "create_proposal_draft",
            "submit_proposal",
        ],
        "portfolio": ["search_evidence", "get_case_study", "list_skills"],
    },
}


@dataclass
class DegradedState:
    """Shared signal: which servers are currently failing and since when. The UI reads this."""

    failing: dict[str, float] = field(default_factory=dict)
    last_error: dict[str, str] = field(default_factory=dict)

    def mark(self, server: str, error: str) -> None:
        self.failing.setdefault(server, time.time())
        self.last_error[server] = error[:300]

    def clear(self, server: str) -> None:
        self.failing.pop(server, None)
        self.last_error.pop(server, None)

    def snapshot(self) -> dict[str, Any]:
        return {
            s: {"since": t, "error": self.last_error.get(s, "")} for s, t in self.failing.items()
        }


DEGRADED = DegradedState()


def server_connections() -> dict[str, dict[str, Any]]:
    env = settings.env()
    headers = {"Authorization": f"Bearer {env.mcp_bearer_token}"}
    conns: dict[str, dict[str, Any]] = {
        "portfolio": {
            "transport": "streamable_http",
            "url": env.mcp_portfolio_url,
            "headers": headers,
        },
        "marketplace": {
            "transport": "streamable_http",
            "url": env.mcp_marketplace_url,
            "headers": headers,
        },
        "workspace": {
            "transport": "streamable_http",
            "url": env.mcp_workspace_url,
            "headers": headers,
        },
    }
    if env.github_token:
        conns["github"] = {
            "transport": "streamable_http",
            "url": env.github_mcp_url,
            "headers": {"Authorization": f"Bearer {env.github_token}"},
        }
    return conns


def _wrap(tool: BaseTool, server: str, timeout: float, retries: int) -> BaseTool:
    """Timeout + bounded retry + degraded-mode bookkeeping around one MCP tool."""

    async def run(**kwargs: Any) -> Any:
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                out = await asyncio.wait_for(tool.ainvoke(kwargs), timeout=timeout)
                DEGRADED.clear(server)
                return out
            except TimeoutError as exc:
                last = exc
                DEGRADED.mark(server, f"timeout after {timeout}s")
            except Exception as exc:  # noqa: BLE001
                last = exc
                text = str(exc).lower()
                transient = any(
                    k in text
                    for k in (
                        "unavailable",
                        "rate limited",
                        "retry after",
                        "timeout",
                        "connection",
                        "503",
                        "502",
                    )
                )
                if not transient:
                    raise
                DEGRADED.mark(server, str(exc))
            if attempt < retries:
                await asyncio.sleep(min(20.0, 1.5 * 2**attempt))
        assert last is not None
        raise last

    return StructuredTool.from_function(
        coroutine=run,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        return_direct=False,
    )


class ToolProvider:
    """Loads tools from MCP servers once and hands each agent its allowlisted subset."""

    def __init__(
        self, loader: Callable[[], Awaitable[dict[str, list[BaseTool]]]] | None = None
    ) -> None:
        self._loader = loader
        self._tools: dict[str, dict[str, BaseTool]] | None = None
        self._lock = asyncio.Lock()

    async def _default_loader(self) -> dict[str, list[BaseTool]]:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(server_connections())
        out: dict[str, list[BaseTool]] = {}
        for server in server_connections():
            try:
                out[server] = await asyncio.wait_for(
                    client.get_tools(server_name=server), timeout=20
                )
                DEGRADED.clear(server)
            except Exception as exc:  # noqa: BLE001
                log.warning("MCP server %s unavailable at load: %s", server, exc)
                DEGRADED.mark(server, str(exc))
                out[server] = []
        return out

    async def load(self, force: bool = False) -> None:
        async with self._lock:
            if self._tools is not None and not force:
                return
            raw = await (self._loader or self._default_loader)()
            cfg = settings.config().budgets
            timeout = float(cfg.get("per_node_timeout_seconds", 90)) / 3
            retries = int(cfg.get("per_node_retries", 2))
            self._tools = {
                server: {t.name: _wrap(t, server, timeout, retries) for t in tools}
                for server, tools in raw.items()
            }

    async def tools_for(self, agent: str) -> list[BaseTool]:
        await self.load()
        assert self._tools is not None
        allow = AGENT_TOOLS.get(agent, {})
        out: list[BaseTool] = []
        for server, names in allow.items():
            available = self._tools.get(server, {})
            for n in names:
                if n in available:
                    out.append(available[n])
                else:
                    log.debug("agent %s: tool %s/%s not available", agent, server, n)
        return out

    async def tool(self, server: str, name: str) -> BaseTool:
        await self.load()
        assert self._tools is not None
        try:
            return self._tools[server][name]
        except KeyError as exc:
            raise RuntimeError(
                f"MCP tool {server}/{name} is not available (degraded: {DEGRADED.snapshot()})"
            ) from exc


async def in_process_loader() -> dict[str, list[BaseTool]]:
    """Mount our three servers in-process (no HTTP) and load their tools. Used by tests and `make demo`."""
    from langchain_mcp_adapters.tools import load_mcp_tools
    from mcp.shared.memory import create_connected_server_and_client_session

    from mcp_servers.marketplace.server import build_server as build_marketplace
    from mcp_servers.portfolio.server import build_server as build_portfolio
    from mcp_servers.workspace.server import build_server as build_workspace

    out: dict[str, list[BaseTool]] = {}
    for name, builder in (
        ("portfolio", build_portfolio),
        ("marketplace", build_marketplace),
        ("workspace", build_workspace),
    ):
        server = builder()

        async def make_tools(server=server):  # type: ignore[no-untyped-def]
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                return await load_mcp_tools(session)

        # load_mcp_tools needs a live session per call; wrap each tool to open one on demand
        tools = await make_tools()
        wrapped: list[BaseTool] = []
        for t in tools:

            def _bind(tool_name: str, srv=server):  # type: ignore[no-untyped-def]
                async def call(**kwargs: Any) -> Any:
                    async with create_connected_server_and_client_session(
                        srv._mcp_server
                    ) as session:
                        res = await session.call_tool(tool_name, kwargs)
                        error = (
                            (res.content[0].text if res.content else "tool error")
                            if res.isError
                            else None
                        )
                        value = (
                            res.structuredContent
                            if res.structuredContent is not None
                            else (res.content[0].text if res.content else None)
                        )
                    if error is not None:  # raise outside the session so no ExceptionGroup wraps it
                        raise RuntimeError(error)
                    return value

                return call

            wrapped.append(
                StructuredTool.from_function(
                    coroutine=_bind(t.name),
                    name=t.name,
                    description=t.description,
                    args_schema=t.args_schema,
                )
            )
        out[name] = wrapped
    return out


PROVIDER = ToolProvider()
