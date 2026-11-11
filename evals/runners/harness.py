"""Shared evaluation harness: run the real bid-graph nodes on dev jobs through the in-process MCP
servers, with timing and token accounting. Evaluation code calls the same node functions the
graph uses, so it measures the shipped logic.

The harness never submits anything unless a runner explicitly asks for a GigSim outcome run, and
then only against the simulator.
"""

from __future__ import annotations

import asyncio
import json
import random
import statistics
import time
from pathlib import Path
from typing import Any

from agent.deps import Deps
from agent.mcp_client import ToolProvider, in_process_loader
from agent.nodes import (
    analyst,
    compliance,
    critic,
    decision,
    fit_matcher,
    pricing,
    risk_assessor,
    verifier,
    writer,
)
from agent.settings import ROOT
from agent.state import BidState

DATASETS = ROOT / "evals/datasets"
RESULTS = ROOT / "evals/results"
PERSONAS = ("ai_ml", "fullstack", "data_analyst")
PREFS = {
    "hourly_rate": 55,
    "hourly_floor": 20,
    "min_project_budget": 50,
    "weekly_connects_budget": 400,
}


def load_dev(persona: str) -> list[dict[str, Any]]:
    p = DATASETS / f"dev_{persona}.jsonl"
    return [json.loads(line) for line in p.open(encoding="utf-8")] if p.exists() else []


def sample_jobs(
    n_per_persona: int,
    seed: int = 7,
    personas: tuple[str, ...] = PERSONAS,
    require_label: bool = True,
) -> list[dict[str, Any]]:
    """Stratified sample: per persona, keep the class mix of bid / skip / scam / injection."""
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    for p in personas:
        rows = [r for r in load_dev(p) if (r.get("gold_decision") or not require_label)]
        buckets = {
            "scam": [r for r in rows if r.get("gold_scam")],
            "injection": [r for r in rows if r.get("gold_injection")],
            "bid": [
                r for r in rows if r.get("gold_decision") == "bid" and not r.get("gold_injection")
            ],
            "skip": [
                r for r in rows if r.get("gold_decision") == "skip" and not r.get("gold_scam")
            ],
        }
        share = {"bid": 0.4, "skip": 0.25, "scam": 0.2, "injection": 0.15}
        picked: list[dict[str, Any]] = []
        for k, frac in share.items():
            b = buckets[k]
            rng.shuffle(b)
            picked += b[: max(1, round(n_per_persona * frac))]
        out += picked[:n_per_persona]
    return out


def make_deps() -> Deps:
    return Deps(tools=ToolProvider(loader=in_process_loader))


def state_for(row: dict[str, Any]) -> BidState:
    job = dict(row["job"])
    job.pop("persona", None)
    return {
        "thread_id": f"eval-{row['job_id']}",
        "user_id": "eval",
        "persona": row["persona"],
        "job_id": row["job_id"],
        "job": job,
        "user_prefs": {**PREFS, "persona": row["persona"]},
        "style_rules": [],
        "outcome_hints": [],
        "revision_count": 0,
        "errors": [],
        "trace": [],
        "usage": {},
        "steps": 0,
    }


def _merge(state: BidState, update: dict[str, Any]) -> None:
    for k, v in update.items():
        if k == "trace":
            state["trace"] = [*state.get("trace", []), *v]
        elif k == "usage":
            u = dict(state.get("usage", {}))
            for kk, vv in v.items():
                u[kk] = u.get(kk, 0) + vv
            state["usage"] = u
        elif k == "errors":
            state["errors"] = [*state.get("errors", []), *v]
        elif k == "steps":
            state["steps"] = state.get("steps", 0) + v
        else:
            state[k] = v  # type: ignore[literal-required]


async def analyse(row: dict[str, Any], deps: Deps) -> tuple[BidState, float]:
    """Parallel analysis + decision + pricing, exactly as in the bid graph."""
    st = state_for(row)
    t0 = time.perf_counter()
    results = await asyncio.gather(
        analyst.run(st, deps),
        risk_assessor.run(st, deps),
        fit_matcher.run(st, deps),
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, BaseException):
            st["errors"] = [*st.get("errors", []), f"{type(r).__name__}: {r}"[:300]]
        else:
            _merge(st, r)
    _merge(st, await decision.run(st, deps))
    if st.get("decision", {}).get("decision") == "bid":
        _merge(st, await pricing.run(st, deps))
    return st, time.perf_counter() - t0


async def draft(
    st: BidState, deps: Deps, max_revisions: int | None = None
) -> tuple[BidState, float]:
    """Writer -> verifier -> critic loop -> compliance, as in the bid graph (no approval, no send)."""
    t0 = time.perf_counter()
    max_rev = (
        int(deps.config.budgets.get("max_revisions", 2)) if max_revisions is None else max_revisions
    )
    while True:
        _merge(st, await writer.run(st, deps))
        st.setdefault("_first_draft", st["proposal_draft"])  # type: ignore[typeddict-item]
        _merge(st, await verifier.run(st, deps))
        _merge(st, await critic.run(st, deps))
        if st.get("status") != "drafting" or int(st.get("revision_count", 0)) > max_rev:
            break
    _merge(st, await compliance.run(st, deps))
    return st, time.perf_counter() - t0


def pctl(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 3)


def summary_stats(xs: list[float]) -> dict[str, float | None]:
    return {
        "p50": pctl(xs, 0.5),
        "p95": pctl(xs, 0.95),
        "mean": round(statistics.mean(xs), 3) if xs else None,
    }


# rough hosted open-model prices (USD per 1M tokens); recorded with every result for transparency
PRICE_PER_M = {"input": 0.15, "output": 0.60}


def cost(usage: dict[str, int]) -> float:
    return round(
        (
            usage.get("input_tokens", 0) * PRICE_PER_M["input"]
            + usage.get("output_tokens", 0) * PRICE_PER_M["output"]
        )
        / 1_000_000,
        6,
    )


def write_result(name: str, payload: dict[str, Any]) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "price_per_million_tokens_usd": PRICE_PER_M,
        **payload,
    }
    path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
