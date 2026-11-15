"""Workspace MCP server: calendar free slots, tentative interview holds, email drafts.

Backed by a local mock store (data/processed/workspace.json) so it works offline; the tool
surface is what an agent sees, so swapping in Google Calendar/Gmail later changes only this file.

Run: uv run python -m mcp_servers.workspace.server --http   (:8103/mcp)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from agent import settings
from mcp_servers.common.auth import make_token_verifier, token_auth_settings
from mcp_servers.common.descriptions import tool_description

READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


class Slot(BaseModel):
    start: str
    end: str
    timezone: str = "UTC"


class FreeSlotsResult(BaseModel):
    days: int
    slot_minutes: int
    slots: list[Slot]


class Hold(BaseModel):
    hold_id: str
    start: str
    end: str
    title: str
    status: Literal["tentative", "confirmed", "cancelled"] = "tentative"
    with_client: str | None = None
    thread_id: str | None = None


class EmailDraft(BaseModel):
    draft_id: str
    to: str
    subject: str
    body: str
    created_at: str
    status: Literal["draft"] = "draft"


class WorkspaceStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.ROOT / "data/processed/workspace.json"
        self._lock = threading.Lock()
        self.data: dict[str, Any] = {"holds": {}, "drafts": {}, "busy": [], "idempotency": {}}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def free_slots(
        self,
        days: int,
        slot_minutes: int,
        work_start: int,
        work_end: int,
        start_from: dt.datetime | None = None,
    ) -> list[Slot]:
        now = start_from or dt.datetime.now(dt.UTC).replace(tzinfo=None)
        busy = [
            (dt.datetime.fromisoformat(h["start"]), dt.datetime.fromisoformat(h["end"]))
            for h in self.data["holds"].values()
            if h["status"] != "cancelled"
        ]
        busy += [
            (dt.datetime.fromisoformat(b["start"]), dt.datetime.fromisoformat(b["end"]))
            for b in self.data["busy"]
        ]
        slots: list[Slot] = []
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for d in range(days):
            cur = day + dt.timedelta(days=d)
            if cur.weekday() >= 5:
                continue
            t = cur.replace(hour=work_start)
            end = cur.replace(hour=work_end)
            while t + dt.timedelta(minutes=slot_minutes) <= end:
                t_end = t + dt.timedelta(minutes=slot_minutes)
                if t > now and not any(bs < t_end and be > t for bs, be in busy):
                    slots.append(Slot(start=t.isoformat(), end=t_end.isoformat()))
                t = t_end
        return slots


def build_server(store: WorkspaceStore | None = None, *, http_auth: bool = False) -> FastMCP:
    ws = store or WorkspaceStore()
    kwargs: dict[str, Any] = {}
    if http_auth:
        kwargs["token_verifier"] = make_token_verifier()
        kwargs["auth"] = token_auth_settings()
    mcp = FastMCP(
        "gigbid-workspace",
        instructions="The freelancer's calendar and email drafts. Holds are tentative until the human confirms; email drafts are never sent by this server.",
        host="0.0.0.0",
        port=int(os.environ.get("MCP_WORKSPACE_PORT", "8103")),
        streamable_http_path="/mcp",
        **kwargs,
    )

    @mcp.tool(
        annotations=READ,
        title="List free calendar slots",
        description=tool_description("get_free_slots"),
    )
    def get_free_slots(
        days: int = Field(default=5, ge=1, le=14),
        slot_minutes: int = Field(default=30, ge=15, le=120),
        work_start_hour: int = Field(default=9, ge=0, le=23),
        work_end_hour: int = Field(default=17, ge=1, le=24),
        max_slots: int = Field(default=8, ge=1, le=40),
    ) -> FreeSlotsResult:
        """Free interview slots on working days within the next `days` days (UTC)."""
        slots = ws.free_slots(days, slot_minutes, work_start_hour, work_end_hour)[:max_slots]
        return FreeSlotsResult(days=days, slot_minutes=slot_minutes, slots=slots)

    @mcp.tool(
        annotations=WRITE,
        title="Create a tentative interview hold",
        description=tool_description("create_interview_hold"),
    )
    def create_interview_hold(
        start: str = Field(description="ISO-8601 start, UTC"),
        end: str = Field(description="ISO-8601 end, UTC"),
        title: str = Field(min_length=3, max_length=120),
        idempotency_key: str = Field(min_length=8, max_length=128),
        with_client: str | None = None,
        thread_id: str | None = None,
    ) -> Hold:
        """Block a tentative slot for an interview. Idempotent on `idempotency_key`."""
        with ws._lock:
            if idempotency_key in ws.data["idempotency"]:
                return Hold.model_validate(
                    ws.data["holds"][ws.data["idempotency"][idempotency_key]]
                )
            s, e = dt.datetime.fromisoformat(start), dt.datetime.fromisoformat(end)
            if e <= s:
                raise ValueError("end must be after start")
            for h in ws.data["holds"].values():
                if (
                    h["status"] != "cancelled"
                    and dt.datetime.fromisoformat(h["start"]) < e
                    and dt.datetime.fromisoformat(h["end"]) > s
                ):
                    raise ValueError(f"slot overlaps existing hold {h['hold_id']}")
            hold = Hold(
                hold_id="hold_" + uuid.uuid4().hex[:10],
                start=s.isoformat(),
                end=e.isoformat(),
                title=title,
                with_client=with_client,
                thread_id=thread_id,
            )
            ws.data["holds"][hold.hold_id] = hold.model_dump()
            ws.data["idempotency"][idempotency_key] = hold.hold_id
            ws.save()
            return hold

    @mcp.tool(
        annotations=WRITE,
        title="Create an email draft",
        description=tool_description("create_email_draft"),
    )
    def create_email_draft(
        to: str = Field(min_length=3, max_length=200),
        subject: str = Field(min_length=1, max_length=200),
        body: str = Field(min_length=1, max_length=8000),
        idempotency_key: str = Field(min_length=8, max_length=128),
    ) -> EmailDraft:
        """Save an email as a draft for the human to review and send. Never sends."""
        with ws._lock:
            if idempotency_key in ws.data["idempotency"]:
                return EmailDraft.model_validate(
                    ws.data["drafts"][ws.data["idempotency"][idempotency_key]]
                )
            d = EmailDraft(
                draft_id="draft_" + uuid.uuid4().hex[:10],
                to=to,
                subject=subject,
                body=body,
                created_at=dt.datetime.now(dt.UTC).isoformat(),
            )
            ws.data["drafts"][d.draft_id] = d.model_dump()
            ws.data["idempotency"][idempotency_key] = d.draft_id
            ws.save()
            return d

    @mcp.tool(
        annotations=READ,
        title="List holds and drafts",
        description=tool_description("list_workspace_items"),
    )
    def list_workspace_items() -> dict[str, Any]:
        """All interview holds and email drafts."""
        return {
            "holds": list(ws.data["holds"].values()),
            "drafts": list(ws.data["drafts"].values()),
        }

    return mcp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true")
    args = ap.parse_args()
    build_server(http_auth=args.http).run(transport="streamable-http" if args.http else "stdio")


if __name__ == "__main__":
    main()
