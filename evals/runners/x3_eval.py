"""Signature extension X3 evaluation: does the Portfolio builder recover what written case studies
give retrieval, and is what it writes true?

For each persona with repositories, three indexes are compared on the dev jobs whose gold projects
include a repository project:
  original - the persona corpus as generated (written case studies for every project)
  base     - the same corpus with the case studies of repository projects removed
             (a freelancer who has code on GitHub but never wrote it up)
  built    - base plus the case studies the builder generated from those repositories' code

Builder quality, per case study: claims, labels before repair, unsupported rate after, facts cited,
and library recall / precision against the project's own metadata (did reading the code find the
stack the project actually used?).

The builder runs through its real graph up to the review interrupt (the evaluation then writes the
drafts with the original project ids so retrieval can be scored at project level).

  uv run python -m evals.runners.x3_eval [--personas ai_ml,fullstack,data_analyst] [--variant v2_hybrid]
The builder output per persona is kept in x3_eval_rows.jsonl, so a run stopped by a daily model
cap resumes with the next persona (exit status 3 = partial, rerun later).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import statistics
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from agent import settings
from agent.deps import Deps
from agent.graphs import portfolio_builder_graph as pbg
from evals.runners.harness import QuotaGuard, RowLog, cost, write_result
from evals.runners.rag_eval import load_dev, metrics
from rag.index.pg import ChunkStore
from rag.ingest.cli import ingest_persona
from rag.retriever import Resources, build_retriever

PERSONAS_ROOT = settings.ROOT / "data/personas"


def prepare_base(persona: str) -> tuple[Path, dict[str, str]]:
    """Copy the persona without case studies of repository projects; return repo -> project id."""
    src = PERSONAS_ROOT / persona
    base = PERSONAS_ROOT / f"x3_{persona}_base"
    if base.exists():
        shutil.rmtree(base)
    shutil.copytree(src, base)
    repo_pid: dict[str, str] = {}
    for repo in (src / "repos").iterdir():
        pidf = repo / ".project_id"
        if pidf.exists():
            repo_pid[repo.name] = pidf.read_text(encoding="utf-8").strip()
    removed = 0
    for cs in (base / "case_studies").glob("*.md"):
        head = cs.read_text(encoding="utf-8")[:300]
        if any(f"project_id: {pid}\n" in head for pid in repo_pid.values()):
            cs.unlink()
            removed += 1
    print(f"  {persona}: base corpus without {removed} repo case studies")
    return base, repo_pid


async def build_drafts(
    persona: str, repo_root: Path
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    graph = pbg.build_graph(Deps(), checkpointer=InMemorySaver(), reindex=False)
    cfg = pbg.builder_config(f"x3-{persona}")
    out = await graph.ainvoke(
        pbg.initial_builder_state(
            thread_id=f"x3-{persona}",
            owner=f"demo-{persona}",
            persona_key=f"x3_{persona}_tmp",
            source_kind="local",
            local_root=str(repo_root),
            max_repos=20,
        ),
        cfg,
    )
    payload = out["__interrupt__"][0].value if out.get("__interrupt__") else {"drafts": []}
    return payload.get("drafts", []), out.get("usage", {})


def write_built(
    persona: str, base: Path, drafts: list[dict[str, Any]], repo_pid: dict[str, str]
) -> Path:
    built = PERSONAS_ROOT / f"x3_{persona}_built"
    if built.exists():
        shutil.rmtree(built)
    shutil.copytree(base, built)
    for d in drafts:
        pid = repo_pid.get(d["repo"])
        if not pid:
            continue
        prof = d.get("profile", {})
        front = f"---\nproject_id: {pid}\nyear: {prof.get('year') or ''}\nclient_industry: \nskills: {json.dumps(prof.get('languages', []))}\nlibraries: {json.dumps(prof.get('libraries', []))}\nsource: portfolio_builder\nverified: true\n---\n\n"
        (built / "case_studies" / f"gh_{pbg.slug(d['repo'])}.md").write_text(
            front + d["markdown"].strip() + "\n", encoding="utf-8"
        )
    return built


def library_scores(
    persona: str, drafts: list[dict[str, Any]], repo_pid: dict[str, str]
) -> list[dict[str, Any]]:
    projects = {
        p["id"]: p
        for p in json.loads((PERSONAS_ROOT / persona / "projects.json").read_text(encoding="utf-8"))
    }
    rows = []
    for d in drafts:
        proj = projects.get(repo_pid.get(d["repo"], ""), {})
        truth = {x.lower() for x in proj.get("libraries", []) + proj.get("skills", [])}
        found = {x.lower() for x in d.get("profile", {}).get("libraries", [])}
        hit = {f for f in found if any(f in t or t in f for t in truth)}
        v = d.get("verification", {})
        rows.append(
            {
                "repo": d["repo"],
                "project_id": repo_pid.get(d["repo"]),
                "claims": v.get("claims"),
                "labels_before": v.get("before"),
                "unsupported_rate_before": v.get("unsupported_rate_before"),
                "unsupported_rate_after": v.get("unsupported_rate_after"),
                "removed": v.get("removed"),
                "facts_total": v.get("facts_total"),
                "facts_cited": v.get("facts_cited"),
                "libraries_found": sorted(found),
                "libraries_in_metadata": sorted(truth),
                "library_precision": round(len(hit) / len(found), 3) if found else None,
                "library_recall": round(
                    len({t for t in truth if any(f in t or t in f for f in found)}) / len(truth), 3
                )
                if truth
                else None,
                "words": len(d.get("markdown", "").split()),
                "seconds": d.get("seconds"),
            }
        )
    return rows


def retrieval(
    persona_keys: dict[str, str], gold_persona: str, repo_pids: set[str], variant: str
) -> dict[str, Any]:
    rows = [r for r in load_dev(gold_persona, None) if set(r["gold_projects"]) & repo_pids]
    res = Resources()
    retr = build_retriever(variant, res)
    out: dict[str, Any] = {"n_jobs": len(rows)}
    for label, key in persona_keys.items():
        ms = []
        for r in rows:
            ev = retr.retrieve(r["job"], key, k=12)
            ev = [e for e in ev if not (e.doc_type == "proposal" and e.job_id == r["job_id"])][:10]
            ms.append(metrics([e.project_id for e in ev], set(r["gold_projects"])))
        out[label] = {k: round(statistics.mean(m[k] for m in ms), 4) for k in ms[0]} if ms else None
    return out


async def run_persona(
    persona: str, variant: str, store: ChunkStore, log: RowLog, guard: QuotaGuard
) -> dict[str, Any] | None:
    """None when a daily model cap stopped the builder (the persona is redone on the next run)."""
    base, repo_pid = prepare_base(persona)
    saved = log.get(persona)
    if saved:  # the builder output is the expensive part; retrieval scoring is local and cheap
        drafts, usage = saved["drafts"], saved["usage"]
    else:
        mark = guard.mark()
        drafts, usage = await build_drafts(persona, PERSONAS_ROOT / persona / "repos")
        if guard.spoiled(mark):
            return None
        log.add(persona, {"persona": persona, "drafts": drafts, "usage": usage})
    print(f"  {persona}: {len(drafts)} case studies drafted from {len(repo_pid)} repositories")
    built = write_built(persona, base, drafts, repo_pid)
    for d in (base, built):
        await asyncio.to_thread(lambda d=d: ingest_persona(store, d))
    rtv = await asyncio.to_thread(
        lambda: retrieval(
            {"original": persona, "base": base.name, "built": built.name},
            persona,
            set(repo_pid.values()),
            variant,
        )
    )
    quality = library_scores(persona, drafts, repo_pid)
    return {
        "repositories": len(repo_pid),
        "drafted": len(drafts),
        "retrieval": rtv,
        "case_studies": quality,
        "tokens": sum(usage.values()),
        "cost_usd": cost(usage),
    }


def aggregate(per: dict[str, Any]) -> dict[str, Any]:
    cs = [c for p in per.values() for c in p["case_studies"]]

    def mean(key: str) -> float | None:
        xs = [c[key] for c in cs if c.get(key) is not None]
        return round(statistics.mean(xs), 3) if xs else None

    rec = {}
    for label in ("original", "base", "built"):
        vals = [p["retrieval"][label] for p in per.values() if p["retrieval"].get(label)]
        weights = [p["retrieval"]["n_jobs"] for p in per.values() if p["retrieval"].get(label)]
        if vals:
            rec[label] = {
                k: round(
                    sum(v[k] * w for v, w in zip(vals, weights, strict=True)) / sum(weights), 4
                )
                for k in vals[0]
            }
    return {
        "case_studies": len(cs),
        "unsupported_rate_before": mean("unsupported_rate_before"),
        "unsupported_rate_after": mean("unsupported_rate_after"),
        "claims_per_case_study": mean("claims"),
        "facts_cited_per_case_study": mean("facts_cited"),
        "library_recall": mean("library_recall"),
        "library_precision": mean("library_precision"),
        "retrieval_weighted": rec,
        "n_jobs": sum(p["retrieval"]["n_jobs"] for p in per.values()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--personas", default="ai_ml,fullstack,data_analyst")
    ap.add_argument("--variant", default="v2_hybrid")
    ap.add_argument("--fresh", action="store_true", help="discard saved builder output")
    args = ap.parse_args()
    store = ChunkStore()
    log, guard = RowLog("x3_eval", fresh=args.fresh), QuotaGuard()
    personas = [x for x in args.personas.split(",") if x]
    per = {}
    for p in personas:
        res = asyncio.run(run_persona(p, args.variant, store, log, guard))
        if res is None:
            if guard.stopped:
                break
            continue
        per[p] = res
    log.collect(personas, guard)  # exits with status 3 if a persona is still missing
    agg = aggregate(per)
    path = write_result("x3_eval", {"config": vars(args), "overall": agg, "personas": per})
    print(json.dumps(agg, indent=2))
    print(f"-> {path}")


if __name__ == "__main__":
    main()
