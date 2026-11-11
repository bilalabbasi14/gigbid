"""Where the portfolio builder reads repositories from.

GitHubMCPSource reads through the official GitHub MCP server (remote endpoint, read-only repos
toolset) using the tools allowlisted for the `portfolio_builder` agent. LocalRepoSource reads a
directory of repositories (the persona corpora, or a checked-out folder) and is used for the
evaluation and offline demos. Both expose the same small interface.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".idea",
    ".vscode",
}


@dataclass
class RepoRef:
    name: str
    description: str = ""
    language: str | None = None
    stars: int = 0
    updated_at: str | None = None
    fork: bool = False
    url: str | None = None


@dataclass
class CommitStats:
    count: int = 0
    first: str | None = None
    last: str | None = None
    authors: list[str] = field(default_factory=list)


class RepoSource(Protocol):
    kind: str
    owner: str

    async def list_repos(self, limit: int) -> list[RepoRef]: ...
    async def tree(self, repo: str) -> list[str]: ...
    async def read(self, repo: str, path: str, max_chars: int = 6000) -> str | None: ...
    async def commits(self, repo: str) -> CommitStats: ...


class LocalRepoSource:
    kind = "local"

    def __init__(self, root: Path, owner: str = "local") -> None:
        self.root = Path(root)
        self.owner = owner

    async def list_repos(self, limit: int) -> list[RepoRef]:
        repos = []
        for d in sorted(p for p in self.root.iterdir() if p.is_dir() and p.name not in SKIP_DIRS):
            readme = d / "README.md"
            desc = ""
            if readme.exists():
                lines = [
                    ln.strip()
                    for ln in readme.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if ln.strip() and not ln.startswith("#")
                ]
                desc = lines[0][:200] if lines else ""
            repos.append(RepoRef(name=d.name, description=desc))
        return repos[:limit]

    async def tree(self, repo: str) -> list[str]:
        base = self.root / repo
        out = []
        for p in base.rglob("*"):
            if (
                p.is_file()
                and not any(part in SKIP_DIRS for part in p.relative_to(base).parts)
                and not p.name.startswith(".project_id")
            ):
                out.append(p.relative_to(base).as_posix())
        return sorted(out)

    async def read(self, repo: str, path: str, max_chars: int = 6000) -> str | None:
        p = self.root / repo / path
        if not p.is_file():
            return None
        return p.read_text(encoding="utf-8", errors="ignore")[:max_chars]

    async def commits(self, repo: str) -> CommitStats:
        return CommitStats()


def _parse(out: Any) -> Any:
    """MCP tool output -> Python object (structured content, JSON text, or content blocks)."""
    if isinstance(out, dict | list) and not (
        isinstance(out, list)
        and out
        and isinstance(out[0], dict)
        and "type" in out[0]
        and "text" in out[0]
    ):
        return out
    if isinstance(out, list):  # content blocks
        texts = [b.get("text", "") for b in out if isinstance(b, dict)]
        out = "\n".join(t for t in texts if t)
    if isinstance(out, str):
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return out
    return out


class GitHubMCPSource:
    """Reads a GitHub account through the GitHub MCP server's read-only repository tools."""

    kind = "github"

    def __init__(self, call_tool, owner: str) -> None:  # type: ignore[no-untyped-def]
        # call_tool(name, **args) -> raw tool output; injected so the agent allowlist is enforced
        self._call = call_tool
        self.owner = owner

    async def list_repos(self, limit: int) -> list[RepoRef]:
        data = _parse(
            await self._call(
                "search_repositories",
                query=f"user:{self.owner} fork:false",
                perPage=min(100, max(limit * 2, 10)),
                minimal_output=True,
            )
        )
        items = (
            data.get("items", data.get("repositories", []))
            if isinstance(data, dict)
            else data
            if isinstance(data, list)
            else []
        )
        repos = []
        for it in items:
            if not isinstance(it, dict):
                continue
            repos.append(
                RepoRef(
                    name=it.get("name") or str(it.get("full_name", "")).split("/")[-1],
                    description=it.get("description") or "",
                    language=it.get("language"),
                    stars=int(it.get("stargazers_count") or it.get("stars") or 0),
                    updated_at=it.get("updated_at") or it.get("pushed_at"),
                    fork=bool(it.get("fork")),
                    url=it.get("html_url"),
                )
            )
        repos = [r for r in repos if r.name and not r.fork]
        repos.sort(key=lambda r: (r.updated_at or "", r.stars), reverse=True)
        return repos[:limit]

    async def tree(self, repo: str) -> list[str]:
        data = _parse(
            await self._call("get_repository_tree", owner=self.owner, repo=repo, recursive=True)
        )
        entries = data.get("tree", data) if isinstance(data, dict) else data
        out = []
        for e in entries if isinstance(entries, list) else []:
            if isinstance(e, dict) and e.get("type") in ("blob", "file") and e.get("path"):
                if not any(part in SKIP_DIRS for part in e["path"].split("/")):
                    out.append(e["path"])
        return sorted(out)

    async def read(self, repo: str, path: str, max_chars: int = 6000) -> str | None:
        try:
            out = await self._call("get_file_contents", owner=self.owner, repo=repo, path=path)
        except Exception:  # noqa: BLE001 - missing file or binary: treat as absent
            return None
        data = _parse(out)
        if isinstance(data, dict):
            if data.get("encoding") == "base64" and data.get("content"):
                try:
                    return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")[
                        :max_chars
                    ]
                except ValueError:
                    return None
            text = data.get("text") or data.get("content")
            return str(text)[:max_chars] if text else None
        return str(data)[:max_chars] if data else None

    async def commits(self, repo: str) -> CommitStats:
        try:
            data = _parse(
                await self._call("list_commits", owner=self.owner, repo=repo, perPage=100)
            )
        except Exception:  # noqa: BLE001
            return CommitStats()
        items = (
            data
            if isinstance(data, list)
            else data.get("items", [])
            if isinstance(data, dict)
            else []
        )
        dates, authors = [], set()
        for c in items:
            if not isinstance(c, dict):
                continue
            commit = c.get("commit", c)
            d = (commit.get("author") or {}).get("date") or commit.get("date")
            if d:
                dates.append(d)
            a = (c.get("author") or {}).get("login") or (commit.get("author") or {}).get("name")
            if a:
                authors.add(a)
        dates.sort()
        return CommitStats(
            count=len(items),
            first=dates[0] if dates else None,
            last=dates[-1] if dates else None,
            authors=sorted(authors)[:5],
        )
