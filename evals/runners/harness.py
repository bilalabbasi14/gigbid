"""Shared evaluation harness: run the real bid-graph nodes on dev jobs through the in-process MCP
servers, with timing and token accounting. Evaluation code calls the same node functions the
graph uses, so it measures the shipped logic.

The harness never submits anything unless a runner explicitly asks for a GigSim outcome run, and
then only against the simulator.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from agent import llm, settings
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

# Evaluations measure the configured model of each node: no fallback models (agent/llm.py).
os.environ.setdefault("GIGBID_STRICT_MODELS", "1")

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


def hardware() -> dict[str, Any]:
    """CPU, cores and RAM of the machine that ran the evaluation (local-model numbers need it)."""
    import platform

    cpu, ram_gb = platform.processor(), None
    try:
        if sys.platform == "win32":
            import ctypes
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as k:
                cpu = str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()

            class _Mem(ctypes.Structure):
                _fields_ = [  # noqa: RUF012 - ctypes layout
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            m = _Mem()
            m.dwLength = ctypes.sizeof(_Mem)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            ram_gb = round(m.ullTotalPhys / 2**30, 1)
        else:
            info = Path("/proc/meminfo").read_text().split()
            ram_gb = round(int(info[info.index("MemTotal:") + 1]) / 2**20, 1)
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    except Exception:  # noqa: BLE001, S110 - best effort; never fail a run over it
        pass
    return {
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "ram_gb": ram_gb,
        "gpu": None,
        "os": platform.platform(),
    }


def write_result(name: str, payload: dict[str, Any]) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "price_per_million_tokens_usd": PRICE_PER_M,
        "model_profile": os.environ.get("MODEL_PROFILE") or settings.config().models.profile,
        "hardware": hardware(),
        **payload,
    }
    path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------------
# Resumable runs. Free-tier models cap tokens per day, so a long evaluation can stop half-way.
# Each finished item is appended to evals/results/<name>_rows.jsonl; a rerun skips those items.
# Rows are tagged with a fingerprint of everything that decides behaviour (config.yaml, prompts,
# policy pack, run options), so results from an older configuration are never mixed in.


def fingerprint(extra: dict[str, Any] | None = None) -> str:
    h = hashlib.sha1()  # noqa: S324 - identity, not security
    files = sorted((ROOT / "agent/prompts").glob("*.md"))
    files += sorted(f for f in (ROOT / "data/policy_pack").rglob("*") if f.is_file())
    for f in files:
        h.update(f.relative_to(ROOT).as_posix().encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    cfg = settings.config()
    profile = os.environ.get("MODEL_PROFILE") or cfg.models.profile
    runtime = {  # the config sections that change what the agents do (not marketplace polling)
        "models": cfg.models.profiles[profile].model_dump(),
        "nodes": cfg.models.nodes,
        "generation": cfg.models.generation,
        "embeddings": cfg.models.embeddings,
        "reranker": cfg.models.reranker,
        "policy_version": cfg.policy_version,
        **{k: getattr(cfg, k) for k in ("rag", "budgets", "thresholds", "pricing", "guardrails")},
        "extra": extra or {},
    }
    h.update(json.dumps(runtime, sort_keys=True, default=str).encode())
    return h.hexdigest()[:12]


class RowLog:
    """Append-only item results for one evaluation, keyed by item id."""

    def __init__(
        self,
        name: str,
        *,
        extra: dict[str, Any] | None = None,
        fresh: bool = False,
        retry_errors: bool = False,
    ) -> None:
        self.path = RESULTS / f"{name}_rows.jsonl"
        self.fp = fingerprint(extra)
        self.rows: dict[str, dict[str, Any]] = {}
        if fresh and self.path.exists():
            self.path.unlink()
        if not self.path.exists():
            return
        kept, stale = [], 0
        for line in self.path.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("fingerprint") != self.fp:
                stale += 1
                continue
            kept.append(line)
            if not (retry_errors and r.get("error")):
                self.rows[r["key"]] = r
        if stale:  # drop rows of an older configuration so the file only holds comparable rows
            self.path.write_text("".join(kept), encoding="utf-8")
            print(f"  {self.path.name}: dropped {stale} rows from a different configuration")
        if self.rows:
            print(f"  {self.path.name}: resuming with {len(self.rows)} finished items")

    def get(self, key: str) -> dict[str, Any] | None:
        return self.rows.get(key)

    def add(self, key: str, row: dict[str, Any]) -> dict[str, Any]:
        row = {"key": key, "fingerprint": self.fp, **row}
        RESULTS.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        self.rows[key] = row
        return row

    def collect(self, keys: list[str], guard: QuotaGuard) -> list[dict[str, Any]]:
        """Rows for `keys` in order; exits with status 3 if any are missing (rerun to continue)."""
        rows = [self.rows[k] for k in keys if k in self.rows]
        if len(rows) < len(keys):
            why = "a daily model cap was reached" if guard.stopped else "some items did not finish"
            print(
                f"\npartial: {len(rows)}/{len(keys)} items saved in {self.path.name}; {why}. "
                "Rerun the same command later to continue."
            )
            raise SystemExit(3)
        return rows


class QuotaGuard:
    """Stops a run when a daily model cap is hit. The item in flight is discarded: its output came
    from heuristic fallbacks, not the configured models."""

    def __init__(self) -> None:
        self.stopped = False

    @staticmethod
    def mark() -> int:
        return llm.quota_failures()

    def spoiled(self, mark: int, exc: BaseException | None = None) -> bool:
        if llm.quota_failures() > mark or (exc is not None and llm.is_daily_cap(exc)):
            if not self.stopped:
                print("  daily model cap reached: stopping; finished items are saved")
            self.stopped = True
        return self.stopped
