"""Signature extension X3: the Portfolio builder.

    list_repos -> [draft_repo per repository] (parallel, Send) -> review (interrupt) -> save -> END

draft_repo extracts deterministic code facts, drafts a case study that cites a fact for every
claim, then runs the same claim verifier the proposal pipeline uses with the facts as evidence and
repairs unsupported sentences. The human approves, edits or rejects each case study; approved ones
are written into the user's portfolio (marked verified, with their facts) and re-indexed, so the
Portfolio MCP server can cite them in proposals.
"""

from __future__ import annotations

import asyncio
import json
import operator
import re
import time
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from agent import settings
from agent.deps import Deps
from agent.guardrails import delimit_untrusted
from agent.portfolio_builder.facts import Fact, extract_facts
from agent.portfolio_builder.sources import GitHubMCPSource, LocalRepoSource, RepoRef, RepoSource
from agent.state import TraceEvent
from agent.structured import call_prompt
from rag.verify import repair_draft, unsupported_rate, verify_claims

PERSONAS_ROOT = settings.ROOT / "data/personas"
NODE = "portfolio_builder"


def _merge_usage(a: dict[str, int] | None, b: dict[str, int] | None) -> dict[str, int]:
    out = dict(a or {})
    for k, v in (b or {}).items():
        out[k] = out.get(k, 0) + int(v)
    return out


class BuilderState(TypedDict, total=False):
    thread_id: str
    user_id: str
    owner: str
    source_kind: str  # github | local
    local_root: str
    persona_key: str
    max_repos: int
    repos: list[dict[str, Any]]
    drafts: Annotated[list[dict[str, Any]], operator.add]
    decisions: dict[str, Any]
    saved: list[dict[str, Any]]
    status: str
    errors: Annotated[list[str], operator.add]
    trace: Annotated[list[TraceEvent], operator.add]
    usage: Annotated[dict[str, int], _merge_usage]
    steps: Annotated[int, operator.add]


def make_source(state: BuilderState, deps: Deps) -> RepoSource:
    if state.get("source_kind") == "local":
        return LocalRepoSource(Path(state["local_root"]), owner=state.get("owner", "local"))
    trace: list[TraceEvent] = []

    async def call(name: str, **args: Any) -> Any:
        return await deps.call_tool(NODE, "github", name, trace, **args)

    return GitHubMCPSource(call, state["owner"])


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "repo"


# ------------------------------------------------------------------ nodes
def build_graph(
    deps: Deps | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    reindex: bool = True,
):  # type: ignore[no-untyped-def]
    deps = deps or Deps()

    async def list_repos(state: BuilderState) -> dict[str, Any]:
        src = make_source(state, deps)
        try:
            repos = await src.list_repos(int(state.get("max_repos", 6)))
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "needs_attention",
                "errors": [f"listing repositories failed: {exc}"[:300]],
                "steps": 1,
            }
        ev = TraceEvent(
            ts=time.time(),
            node=NODE,
            kind="observation",
            name="list_repos",
            result={"repos": [r.name for r in repos]},
            note=f"{len(repos)} repositories selected from {src.kind}",
        )
        return {
            "repos": [r.__dict__ for r in repos],
            "status": "drafting" if repos else "skipped",
            "trace": [ev],
            "steps": 1,
        }

    def fan_out(state: BuilderState) -> list[Send] | str:
        if state.get("status") != "drafting":
            return END
        return [Send("draft_repo", {**state, "repos": [r]}) for r in state.get("repos", [])]

    async def draft_repo(state: BuilderState) -> dict[str, Any]:
        repo = RepoRef(**state["repos"][0])
        src = make_source(state, deps)
        t0 = time.perf_counter()
        try:
            facts, profile = await extract_facts(src, repo)
            if len(facts) < 3:
                return {
                    "drafts": [
                        {
                            "repo": repo.name,
                            "skipped": True,
                            "reason": "too little verifiable content in the repository",
                        }
                    ],
                    "steps": 1,
                }
            facts_block = "\n".join(
                f"[{f.fact_id}] ({f.kind}) {delimit_untrusted(f.text, 'REPO_TEXT', max_chars=500) if f.kind == 'readme' else f.text} — {f.source}"
                for f in facts
            )
            res = await call_prompt(
                NODE,
                "portfolio_builder",
                invoke=deps.invoke,
                repo=repo.name,
                owner=src.owner,
                description=repo.description or "(none)",
                facts=facts_block,
            )
            text = res.text.strip()
            usage = dict(res.usage)
            evidence = [f.as_evidence(repo.name) for f in facts]
            claims, results = await verify_claims(
                text, evidence, invoke=deps.invoke, use_reranker=deps.use_reranker
            )
            for r in results:
                usage = {k: usage.get(k, 0) + v for k, v in r.usage.items()}
            before = unsupported_rate(claims)
            counts = {
                lab: sum(1 for c in claims if c.label == lab)
                for lab in ("supported", "partly_supported", "unsupported")
            }
            fixed, claims, rres = await repair_draft(text, claims, invoke=deps.invoke)
            if rres:
                usage = {k: usage.get(k, 0) + v for k, v in rres.usage.items()}
            kept = [c for c in claims if c.action != "removed"]
            cited = set(re.findall(r"\[([0-9a-f]{12})\]", fixed))
            title_m = re.search(r"^#\s+(.+)$", fixed, re.M)
            draft = {
                "repo": repo.name,
                "url": repo.url,
                "title": title_m.group(1).strip() if title_m else repo.name,
                "markdown": fixed,
                "first_draft": text,
                "facts": [f.model_dump() for f in facts],
                "claims": [c.model_dump() for c in claims],
                "profile": profile,
                "verification": {
                    "claims": len(claims),
                    "before": counts,
                    "unsupported_rate_before": before,
                    "unsupported_rate_after": unsupported_rate(kept),
                    "removed": sum(1 for c in claims if c.action == "removed"),
                    "facts_cited": len(cited & {f.fact_id for f in facts}),
                    "facts_total": len(facts),
                },
                "seconds": round(time.perf_counter() - t0, 2),
            }
            ev = TraceEvent(
                ts=time.time(),
                node=NODE,
                kind="observation",
                name="draft_repo",
                result={"repo": repo.name, **draft["verification"]},
                note="case study drafted and verified against code facts",
            )
            return {"drafts": [draft], "usage": usage, "trace": [ev], "steps": 1}
        except Exception as exc:  # noqa: BLE001 - one bad repository must not sink the build
            return {
                "drafts": [
                    {
                        "repo": repo.name,
                        "skipped": True,
                        "reason": f"{type(exc).__name__}: {exc}"[:300],
                    }
                ],
                "errors": [f"{repo.name}: {exc}"[:300]],
                "steps": 1,
            }

    async def review(state: BuilderState) -> dict[str, Any]:
        ready = [d for d in state.get("drafts", []) if not d.get("skipped")]
        if not ready:
            return {"status": "skipped", "steps": 1}
        payload = {
            "kind": "portfolio",
            "thread_id": state.get("thread_id"),
            "owner": state.get("owner"),
            "persona_key": state.get("persona_key"),
            "drafts": [{k: v for k, v in d.items() if k != "first_draft"} for d in ready],
            "skipped": [d for d in state.get("drafts", []) if d.get("skipped")],
        }
        raw = interrupt(payload)
        # resume value: {"decisions": {repo: {"action": "approve"|"edit"|"reject", "markdown": "..."}}}
        decisions = (raw or {}).get("decisions", {}) if isinstance(raw, dict) else {}
        return {"decisions": decisions, "status": "saving", "steps": 1}

    async def save(state: BuilderState) -> dict[str, Any]:
        key = state["persona_key"]
        d = PERSONAS_ROOT / key
        (d / "case_studies").mkdir(parents=True, exist_ok=True)
        pj = d / "projects.json"
        projects = json.loads(pj.read_text(encoding="utf-8")) if pj.exists() else []
        saved = []
        for draft in state.get("drafts", []):
            if draft.get("skipped"):
                continue
            dec = state.get("decisions", {}).get(draft["repo"], {})
            if dec.get("action") not in ("approve", "edit"):
                continue
            md = dec.get("markdown") or draft["markdown"]
            existing = next(
                (
                    p
                    for p in projects
                    if p.get("repo_slug") == slug(draft["repo"])
                    and p.get("source") == "portfolio_builder"
                ),
                None,
            )
            pid = existing["id"] if existing else f"p{len(projects) + 1:02d}"
            prof = draft["profile"]
            entry = {
                "id": pid,
                "name": draft["title"],
                "year": prof.get("year"),
                "client_industry": None,
                "skills": prof.get("languages", []),
                "libraries": prof.get("libraries", []),
                "has_repo": True,
                "repo_slug": slug(draft["repo"]),
                "source": "portfolio_builder",
                "verified": True,
                "url": draft.get("url"),
            }
            if existing:
                existing.update(entry)
            else:
                projects.append(entry)
            front = f"---\nproject_id: {pid}\nyear: {prof.get('year') or ''}\nclient_industry: \nskills: {json.dumps(prof.get('languages', []))}\nlibraries: {json.dumps(prof.get('libraries', []))}\nsource: portfolio_builder\nverified: true\nrepository: {state.get('owner')}/{draft['repo']}\n---\n\n"
            (d / "case_studies" / f"gh_{slug(draft['repo'])}.md").write_text(
                front + md.strip() + "\n", encoding="utf-8"
            )
            repo_dir = d / "repos" / slug(draft["repo"])
            repo_dir.mkdir(parents=True, exist_ok=True)
            (repo_dir / ".project_id").write_text(pid + "\n", encoding="utf-8")
            (repo_dir / "FACTS.json").write_text(
                json.dumps(draft["facts"], indent=2), encoding="utf-8"
            )
            readme = "\n".join(f["text"] for f in draft["facts"] if f["kind"] == "readme")
            (repo_dir / "README.md").write_text(
                f"# {draft['title']}\n\n{readme}\n", encoding="utf-8"
            )
            saved.append(
                {"repo": draft["repo"], "project_id": pid, "edited": dec.get("action") == "edit"}
            )
        pj.parent.mkdir(parents=True, exist_ok=True)
        pj.write_text(json.dumps(projects, indent=2, ensure_ascii=False), encoding="utf-8")
        if reindex and saved:
            from rag.index.pg import ChunkStore
            from rag.ingest.cli import ingest_persona

            await asyncio.to_thread(lambda: ingest_persona(ChunkStore(), d))
        ev = TraceEvent(
            ts=time.time(),
            node=NODE,
            kind="observation",
            name="save",
            result={"saved": saved},
            note=f"{len(saved)} verified case studies added to the portfolio",
        )
        return {
            "saved": saved,
            "status": "submitted" if saved else "rejected",
            "trace": [ev],
            "steps": 1,
        }

    g = StateGraph(BuilderState)
    g.add_node("list_repos", list_repos)
    g.add_node("draft_repo", draft_repo)
    g.add_node("review", review)
    g.add_node("save", save)
    g.add_edge(START, "list_repos")
    g.add_conditional_edges("list_repos", fan_out, ["draft_repo", END])
    g.add_edge("draft_repo", "review")
    g.add_conditional_edges(
        "review",
        lambda s: "save" if s.get("status") == "saving" else END,
        {"save": "save", END: END},
    )
    g.add_edge("save", END)
    return g.compile(checkpointer=checkpointer)


def initial_builder_state(
    *,
    thread_id: str,
    owner: str,
    persona_key: str,
    user_id: str = "local",
    source_kind: str = "github",
    local_root: str | None = None,
    max_repos: int = 6,
) -> BuilderState:
    st: BuilderState = {
        "thread_id": thread_id,
        "user_id": user_id,
        "owner": owner,
        "persona_key": persona_key,
        "source_kind": source_kind,
        "max_repos": max_repos,
        "status": "queued",
        "drafts": [],
        "errors": [],
        "trace": [],
        "usage": {},
        "steps": 0,
    }
    if local_root:
        st["local_root"] = local_root
    return st


def builder_config(thread_id: str, *, user_id: str = "local") -> dict[str, Any]:
    return {
        "configurable": {"thread_id": thread_id, "user_id": user_id},
        "recursion_limit": 40,
        "tags": ["portfolio_builder"],
        "metadata": {"thread_id": thread_id, "user_id": user_id},
    }


__all__ = ["Fact", "build_graph", "initial_builder_state", "builder_config"]
