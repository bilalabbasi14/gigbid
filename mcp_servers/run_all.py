"""Run the three GigBid MCP servers over streamable HTTP in one process (dev convenience).

Ports: portfolio 8101, marketplace 8102, workspace 8103 (MCP_*_PORT env to change).
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn

from mcp_servers.marketplace.server import build_server as build_marketplace
from mcp_servers.portfolio.server import build_server as build_portfolio
from mcp_servers.workspace.server import build_server as build_workspace


async def serve(server, port: int) -> None:  # type: ignore[no-untyped-def]
    app = server.streamable_http_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")  # noqa: S104
    await uvicorn.Server(config).serve()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    servers = [
        (build_portfolio(http_auth=True), 8101),
        (build_marketplace(http_auth=True), 8102),
        (build_workspace(http_auth=True), 8103),
    ]
    await asyncio.gather(*(serve(s, p) for s, p in servers))


if __name__ == "__main__":
    asyncio.run(main())
