"""Append-only audit log for MCP tool calls: user, tool, arguments, result, trace id.

Backed by Postgres when DATABASE_URL is reachable, else an append-only JSONL file
(data/processed/audit.jsonl). PII in arguments/results is masked before writing.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from pathlib import Path
from typing import Any

from agent import settings
from agent.pii import mask_pii_in

log = logging.getLogger(__name__)


class AuditLog:
    def __init__(self, path: Path | None = None, use_db: bool | None = None) -> None:
        self.path = path or settings.ROOT / "data/processed/audit.jsonl"
        self._lock = threading.Lock()
        self._engine = None
        self.use_db = use_db if use_db is not None else settings.env().app_env != "test"
        if self.use_db:
            try:
                from sqlalchemy import create_engine, text

                self._engine = create_engine(
                    settings.env().database_url.replace("postgresql://", "postgresql+psycopg://"),
                    pool_pre_ping=True,
                )
                with self._engine.begin() as conn:
                    conn.execute(
                        text(
                            "CREATE TABLE IF NOT EXISTS audit_log (id BIGSERIAL PRIMARY KEY, ts TIMESTAMP NOT NULL, user_id TEXT NOT NULL, tool TEXT NOT NULL, "
                            "args JSONB NOT NULL, result JSONB NOT NULL, trace_id TEXT, ok BOOLEAN NOT NULL)"
                        )
                    )
                    # append-only: revoke UPDATE/DELETE from the application role on this table
                    conn.execute(text("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC"))
            except Exception as exc:  # noqa: BLE001
                log.warning("audit log falling back to file: %s", exc)
                self._engine = None

    def record(
        self,
        *,
        user: str,
        tool: str,
        args: dict[str, Any] | None,
        result: Any,
        trace_id: str = "",
        ok: bool = True,
    ) -> None:
        entry = {
            "ts": dt.datetime.now(dt.UTC).isoformat(),
            "user": user,
            "tool": tool,
            "args": mask_pii_in(args or {}),
            "result": mask_pii_in(_jsonable(result)),
            "trace_id": trace_id or "",
            "ok": ok,
        }
        if self._engine is not None:
            try:
                from sqlalchemy import text

                with self._engine.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO audit_log (ts, user_id, tool, args, result, trace_id, ok) VALUES (:ts, :u, :t, :a, :r, :tr, :ok)"
                        ),
                        {
                            "ts": dt.datetime.now(dt.UTC).replace(tzinfo=None),
                            "u": user,
                            "t": tool,
                            "a": json.dumps(entry["args"]),
                            "r": json.dumps(entry["result"]),
                            "tr": entry["trace_id"],
                            "ok": ok,
                        },
                    )
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("audit db write failed, using file: %s", exc)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def tail(self, n: int = 50) -> list[dict[str, Any]]:
        if self._engine is not None:
            from sqlalchemy import text

            with self._engine.connect() as conn:
                rows = (
                    conn.execute(
                        text(
                            "SELECT ts, user_id, tool, args, result, trace_id, ok FROM audit_log ORDER BY id DESC LIMIT :n"
                        ),
                        {"n": n},
                    )
                    .mappings()
                    .all()
                )
                return [dict(r) for r in rows]
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        return [json.loads(line) for line in lines]


def _jsonable(x: Any) -> Any:
    if hasattr(x, "model_dump"):
        return x.model_dump()
    if isinstance(x, list):
        return [_jsonable(i) for i in x]
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    return x
