"""Schema snapshot test (A7): the full tool surface of our three MCP servers (names, input and
output schemas, annotations) is frozen in tests/contract/snapshots/*.json. Any unintentional
change fails CI. To accept an intentional change: pytest tests/contract --update-mcp-snapshots.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

os.environ.setdefault("APP_ENV", "test")

SNAP_DIR = Path(__file__).parent / "snapshots"


def _marketplace():
    from mcp_servers.marketplace.server import build_server
    from mcp_servers.marketplace.tests.test_marketplace_server import FakePort

    return build_server(FakePort(), audit=_null_audit(), limiter=None)


def _null_audit():
    from mcp_servers.common.audit import AuditLog

    return AuditLog(path=Path(os.devnull), use_db=False)


def _portfolio():
    from mcp_servers.portfolio.server import build_server
    from mcp_servers.portfolio.tests.test_portfolio_server import FakeService

    return build_server(FakeService())


def _workspace(tmp_path):
    from mcp_servers.workspace.server import WorkspaceStore, build_server

    return build_server(WorkspaceStore(path=tmp_path / "ws.json"))


async def surface(server) -> dict:
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        tools = (await client.list_tools()).tools
        out = {}
        for t in sorted(tools, key=lambda t: t.name):
            out[t.name] = {
                "title": t.title,
                "description": t.description,
                "inputSchema": t.inputSchema,
                "outputSchema": t.outputSchema,
                "annotations": t.annotations.model_dump(exclude_none=True)
                if t.annotations
                else None,
            }
        try:
            res = (await client.list_resource_templates()).resourceTemplates
            out["__resource_templates__"] = sorted(r.uriTemplate for r in res)
        except Exception:  # noqa: BLE001
            pass
        try:
            prompts = (await client.list_prompts()).prompts
            out["__prompts__"] = sorted(p.name for p in prompts)
        except Exception:  # noqa: BLE001
            pass
        return out


@pytest.mark.parametrize("name", ["portfolio", "marketplace", "workspace"])
async def test_tool_surface_matches_snapshot(name, tmp_path, request):
    server = {
        "portfolio": _portfolio,
        "marketplace": _marketplace,
        "workspace": lambda: _workspace(tmp_path),
    }[name]()
    current = await surface(server)
    snap = SNAP_DIR / f"{name}.json"
    update = request.config.getoption("--update-mcp-snapshots", default=False)
    if update or not snap.exists():
        SNAP_DIR.mkdir(exist_ok=True)
        snap.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
        if not update:
            pytest.skip(f"snapshot created: {snap}")
    expected = json.loads(snap.read_text(encoding="utf-8"))
    if current != expected:
        added = set(current) - set(expected)
        removed = set(expected) - set(current)
        changed = [k for k in current if k in expected and current[k] != expected[k]]
        pytest.fail(
            f"MCP tool surface of {name} changed. added={sorted(added)} removed={sorted(removed)} changed={changed}. Run `pytest tests/contract --update-mcp-snapshots` if intended."
        )
