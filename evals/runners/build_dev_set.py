"""Build the per-persona dev evaluation sets with gold labels.

Gold sources (all derivable, documented in docs/DATA_CARD.md):
  * past proposals (data/personas/<p>/proposals.jsonl): the persona actually bid on these real
    jobs and cited project ids -> gold_decision=bid, gold_projects=[...]; outcome kept for V4.
  * adversarial gold (evals/datasets/adversarial_gold.jsonl): scams -> skip; injections and
    duplicates keep the decision of their source job.
  * off-persona jobs: jobs classified for another persona with no skill overlap -> skip.
  * fair price band: p25..p75 of the persona x payment-type market quantiles, or the client's
    stated budget range when present.

Writes evals/datasets/dev_<persona>.jsonl. Run: uv run python -m evals.runners.build_dev_set
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
from typing import Any

from agent.settings import ROOT

PERSONAS = ("ai_ml", "fullstack", "data_analyst")
SEED_DIR = ROOT / "gigsim/seed"
DATASETS = ROOT / "evals/datasets"


def load_jobs() -> dict[str, dict[str, Any]]:
    jobs = {}
    with gzip.open(SEED_DIR / "jobs.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            j = json.loads(line)
            jobs[j["job_id"]] = j
    adv = SEED_DIR / "jobs_adversarial.jsonl"
    if adv.exists():
        for line in adv.open(encoding="utf-8"):
            j = json.loads(line)
            jobs[j["job_id"]] = j
    return jobs


def price_band(job: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    pstats = stats["personas"][job["persona"]]
    if job["payment_type"] == "fixed":
        if job.get("budget"):
            lo, hi = job["budget"] * 0.7, job["budget"] * 1.05
        else:
            q = pstats["fixed_budget_usd"] or {"p25": 150, "p75": 600}
            lo, hi = q["p25"], q["p75"]
    else:
        if job.get("hourly_min") and job.get("hourly_max"):
            lo, hi = job["hourly_min"], job["hourly_max"]
        else:
            q = pstats["hourly_min_usd"] or {"p25": 15, "p75": 40}
            lo, hi = q["p25"], q["p75"] * 1.5
    return {"type": job["payment_type"], "low": round(lo, 2), "high": round(hi, 2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--off-persona", type=int, default=25, help="skip-labelled jobs from other personas"
    )
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    jobs = load_jobs()
    stats = json.loads((SEED_DIR / "market_stats.json").read_text(encoding="utf-8"))
    adversarial = [
        json.loads(line) for line in (DATASETS / "adversarial_gold.jsonl").open(encoding="utf-8")
    ]
    DATASETS.mkdir(parents=True, exist_ok=True)

    for persona in PERSONAS:
        rows: list[dict[str, Any]] = []
        pdir = ROOT / "data/personas" / persona
        proposals_path = pdir / "proposals.jsonl"
        if not proposals_path.exists():
            print(f"{persona}: no proposals yet, skipping")
            continue
        profile_skills = {
            s.lower()
            for s in json.loads((pdir / "profile.json").read_text(encoding="utf-8"))["stack"]
        }
        seen: set[str] = set()
        for line in proposals_path.open(encoding="utf-8"):
            p = json.loads(line)
            j = jobs.get(p["job_id"])
            if not j or j["job_id"] in seen:
                continue
            seen.add(j["job_id"])
            rows.append(
                {
                    "job_id": j["job_id"],
                    "persona": persona,
                    "job": j,
                    "gold_decision": "bid",
                    "gold_scam": False,
                    "gold_injection": False,
                    "gold_projects": p.get("project_ids", []),
                    "past_outcome": p.get("outcome"),
                    "fair_price": price_band(j, stats),
                    "label_source": "past_proposal",
                }
            )
        for g in adversarial:
            if g["persona"] != persona:
                continue
            j = jobs.get(g["job_id"])
            if not j:
                continue
            decision = "skip" if g["scam"] else None
            projects: list[str] = []
            if g["kind"] in ("injection", "duplicate"):
                src = g.get("duplicate_of") or next(
                    (r["job_id"] for r in rows if r["job"]["title"] in j["title"]), None
                )
                src_row = next((r for r in rows if r["job_id"] == src), None)
                if src_row:
                    decision, projects = src_row["gold_decision"], src_row["gold_projects"]
            rows.append(
                {
                    "job_id": j["job_id"],
                    "persona": persona,
                    "job": j,
                    "gold_decision": decision,
                    "gold_scam": g["scam"],
                    "gold_injection": g["injection"],
                    "gold_injection_ids": g.get("injection_ids", []),
                    "duplicate_of": g.get("duplicate_of"),
                    "gold_projects": projects,
                    "past_outcome": None,
                    "fair_price": price_band(j, stats),
                    "label_source": "adversarial_gold",
                }
            )
        others = [
            j
            for j in jobs.values()
            if j["persona"] != persona
            and j["source"].startswith("kaggle")
            and not ({s.lower() for s in j["skills"]} & profile_skills)
        ]
        for j in rng.sample(others, k=min(args.off_persona, len(others))):
            rows.append(
                {
                    "job_id": j["job_id"],
                    "persona": persona,
                    "job": j,
                    "gold_decision": "skip",
                    "gold_scam": False,
                    "gold_injection": False,
                    "gold_projects": [],
                    "past_outcome": None,
                    "fair_price": price_band(j, stats),
                    "label_source": "off_persona",
                }
            )
        rng.shuffle(rows)
        out = DATASETS / f"dev_{persona}.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        counts = {
            k: sum(1 for r in rows if r["label_source"] == k)
            for k in ("past_proposal", "adversarial_gold", "off_persona")
        }
        print(f"{persona}: {len(rows)} dev jobs {counts} -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
