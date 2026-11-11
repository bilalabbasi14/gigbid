from __future__ import annotations

import datetime as dt

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_servers.workspace.server import WorkspaceStore, build_server


@pytest.fixture
def server(tmp_path):
    return build_server(WorkspaceStore(path=tmp_path / "ws.json"))


async def test_slots_hold_and_draft(server):
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert tools["get_free_slots"].annotations.readOnlyHint is True
        assert (
            tools["create_interview_hold"].annotations.readOnlyHint is False
            and tools["create_interview_hold"].annotations.destructiveHint is False
        )
        r = await client.call_tool(
            "get_free_slots", {"days": 7, "slot_minutes": 30, "max_slots": 5}
        )
        slots = r.structuredContent["slots"]
        assert 1 <= len(slots) <= 5
        s = slots[0]
        assert dt.datetime.fromisoformat(s["end"]) - dt.datetime.fromisoformat(
            s["start"]
        ) == dt.timedelta(minutes=30)
        h1 = await client.call_tool(
            "create_interview_hold",
            {
                "start": s["start"],
                "end": s["end"],
                "title": "Intro call",
                "idempotency_key": "hold-key-00001",
            },
        )
        h2 = await client.call_tool(
            "create_interview_hold",
            {
                "start": s["start"],
                "end": s["end"],
                "title": "Intro call",
                "idempotency_key": "hold-key-00001",
            },
        )
        assert (
            h1.structuredContent["hold_id"] == h2.structuredContent["hold_id"]
            and h1.structuredContent["status"] == "tentative"
        )
        clash = await client.call_tool(
            "create_interview_hold",
            {
                "start": s["start"],
                "end": s["end"],
                "title": "Other",
                "idempotency_key": "hold-key-00002",
            },
        )
        assert clash.isError and "overlaps" in clash.content[0].text
        r = await client.call_tool(
            "get_free_slots", {"days": 7, "slot_minutes": 30, "max_slots": 5}
        )
        assert s not in r.structuredContent["slots"]
        d = await client.call_tool(
            "create_email_draft",
            {
                "to": "client@example.com",
                "subject": "Interview",
                "body": "Hi",
                "idempotency_key": "mail-key-00001",
            },
        )
        assert d.structuredContent["status"] == "draft"
        items = await client.call_tool("list_workspace_items", {})
        assert (
            len(items.structuredContent["holds"]) == 1
            and len(items.structuredContent["drafts"]) == 1
        )
