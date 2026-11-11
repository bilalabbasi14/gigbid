"""Long-term memory (C2, R7): a LangGraph store with two namespaces per user.

    ("style", user_id)            promoted style rules learned from the user's edits
    ("outcome", user_id, category) promoted hints about what won / got replies per job category
    ("candidates", user_id, kind)  evidence counters that have NOT been promoted yet

Only `promotion_rules.py` writes to "style" and "outcome". Nodes read snapshots through
`style_rules()` / `outcome_hints()` at graph start. Raw tool output never enters the store.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

_STORE: BaseStore | None = None


def get_store() -> BaseStore:
    """Process-wide store. Postgres when DATABASE_URL is reachable (API/worker), else in-memory."""
    global _STORE
    if _STORE is None:
        _STORE = InMemoryStore()
    return _STORE


def set_store(store: BaseStore) -> None:
    global _STORE
    _STORE = store


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


# ---- reads used by the graphs ----
def style_rules(user_id: str, store: BaseStore | None = None) -> list[str]:
    s = store or get_store()
    items = s.search(("style", user_id), limit=50)
    return [
        i.value["rule"]
        for i in sorted(items, key=lambda i: -i.value.get("support", 0))
        if i.value.get("active", True)
    ]


def outcome_hints(user_id: str, category: str | None, store: BaseStore | None = None) -> list[str]:
    s = store or get_store()
    out: list[str] = []
    namespaces = [("outcome", user_id, category)] if category else []
    namespaces.append(("outcome", user_id, "all"))
    for ns in namespaces:
        for i in s.search(ns, limit=20):
            if i.value.get("active", True):
                out.append(i.value["hint"])
    return out[:8]


# ---- memory viewer / delete (Settings screen) ----
def list_memory(user_id: str, store: BaseStore | None = None) -> dict[str, list[dict[str, Any]]]:
    s = store or get_store()
    view: dict[str, list[dict[str, Any]]] = {"style": [], "outcome": [], "candidates": []}
    for i in s.search(("style", user_id), limit=100):
        view["style"].append({"key": i.key, **i.value, "updated_at": str(i.updated_at)})
    for ns in s.list_namespaces(prefix=("outcome", user_id)):
        for i in s.search(ns, limit=100):
            view["outcome"].append(
                {"key": i.key, "category": ns[-1], **i.value, "updated_at": str(i.updated_at)}
            )
    for ns in s.list_namespaces(prefix=("candidates", user_id)):
        for i in s.search(ns, limit=200):
            view["candidates"].append({"key": i.key, "kind": ns[-1], **i.value})
    return view


def delete_memory(
    user_id: str, kind: str, key: str, category: str | None = None, store: BaseStore | None = None
) -> bool:
    s = store or get_store()
    ns = (
        ("style", user_id)
        if kind == "style"
        else ("outcome", user_id, category or "all")
        if kind == "outcome"
        else ("candidates", user_id, category or "style")
    )
    if s.get(ns, key) is None:
        return False
    s.delete(ns, key)
    return True


def clear_memory(user_id: str, store: BaseStore | None = None) -> int:
    s = store or get_store()
    n = 0
    for prefix in (("style", user_id), ("outcome", user_id), ("candidates", user_id)):
        for ns in [prefix, *s.list_namespaces(prefix=prefix)]:
            for i in s.search(ns, limit=500):
                s.delete(ns, i.key)
                n += 1
    return n
