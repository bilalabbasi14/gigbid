"""LLM judge and its calibration against human labels (B4: report Cohen's kappa).

  1. Export a labelling sheet from proposal_eval results (30 proposals, judge scores hidden):
       uv run python -m evals.runners.judge_calibration export --n 30
     -> evals/labeling/judge_sheet.csv  (fill the human_* columns with 1-5)
  2. Score the same proposals with the judge:
       uv run python -m evals.runners.judge_calibration judge
  3. Compute agreement once the sheet is filled:
       uv run python -m evals.runners.judge_calibration kappa
     -> evals/results/judge_calibration.json (quadratic-weighted and unweighted Cohen's kappa per criterion)

The judge prompt is agent/prompts/judge.md (node "judge", large tier). Items are the proposals
GigBid wrote in evals/results/proposal_eval*.json; when there are fewer than --n, the sheet is
filled with the personas' past proposals (data/personas/*/proposals.jsonl), drawn evenly from
won, replied and ignored ones so the items span the quality range. The `source` column says which.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
from typing import Any

from agent.guardrails import delimit_untrusted
from agent.settings import ROOT
from agent.structured import call_structured
from evals.runners.harness import load_dev, write_result

LABEL_DIR = ROOT / "evals/labeling"
SHEET = LABEL_DIR / "judge_sheet.csv"
JUDGED = ROOT / "evals/results/judge_scores.json"
CRITERIA = ["relevance", "specificity", "credibility", "clarity", "next_step", "overall"]


def _past_proposals(seed: int) -> list[dict[str, Any]]:
    """Personas' past proposals, interleaved won / replied / ignored."""
    by_outcome: dict[str, list[dict[str, Any]]] = {}
    for f in sorted((ROOT / "data/personas").glob("*/proposals.jsonl")):
        if f.parent.name.startswith(("_", "x3_")):
            continue
        for line in f.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("cover_letter") and r.get("job_id"):
                r = {**r, "source": f"past_proposal:{f.parent.name}:{r.get('outcome')}"}
                by_outcome.setdefault(str(r.get("outcome")), []).append(r)
    rng = random.Random(seed)
    for rows in by_outcome.values():
        rng.shuffle(rows)
    out = []
    while any(by_outcome.values()):
        for k in sorted(by_outcome):
            if by_outcome[k]:
                out.append(by_outcome[k].pop())
    return out


def proposals(n: int, seed: int) -> list[dict[str, Any]]:
    rows = []
    for f in sorted((ROOT / "evals/results").glob("proposal_eval*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for r in data.get("rows", []):
            if r.get("cover_letter"):
                rows.append({"source": f.name, **r})
    random.Random(seed).shuffle(rows)
    rows += _past_proposals(seed)
    seen, out = set(), []
    for r in rows:
        key = (r["job_id"], r["cover_letter"][:80])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out[:n]


def export(n: int, seed: int) -> None:
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    jobs = {
        r["job_id"]: r["job"] for p in ("ai_ml", "fullstack", "data_analyst") for r in load_dev(p)
    }
    items = proposals(n, seed)
    with SHEET.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "item_id",
                "source",
                "job_id",
                "job_title",
                "job_description",
                "proposal",
                *[f"human_{c}" for c in CRITERIA],
                "notes",
            ]
        )
        for i, r in enumerate(items, 1):
            job = jobs.get(r["job_id"], {})
            w.writerow(
                [
                    f"j{i:02d}",
                    r["source"],
                    r["job_id"],
                    job.get("title", r.get("title", "")),
                    (job.get("description") or "")[:1500],
                    r["cover_letter"],
                    *[""] * len(CRITERIA),
                    "",
                ]
            )
    print(
        f"wrote {len(items)} proposals to {SHEET} - fill human_* with scores 1-5 (see agent/prompts/judge.md for the rubric)"
    )


async def judge_all() -> None:
    from pydantic import BaseModel

    class Scores(BaseModel):
        relevance: int
        specificity: int
        credibility: int
        clarity: int
        next_step: int
        overall: int
        reason: str = ""

    jobs = {
        r["job_id"]: r["job"] for p in ("ai_ml", "fullstack", "data_analyst") for r in load_dev(p)
    }
    rows = list(csv.DictReader(SHEET.open(encoding="utf-8")))
    prop_rows = {(r["job_id"], r["cover_letter"][:80]): r for r in proposals(10_000, 0)}
    out = json.loads(JUDGED.read_text(encoding="utf-8")) if JUDGED.exists() else {}
    for r in rows:
        if r["item_id"] in out:
            continue
        job = jobs.get(r["job_id"], {})
        src = prop_rows.get((r["job_id"], r["proposal"][:80]), {})
        evidence = "\n".join(f"- {t}" for t in src.get("evidence_titles", [])) or "(not recorded)"
        s, res = await call_structured(
            "judge",
            "judge",
            Scores,
            title=r["job_title"],
            job_text=delimit_untrusted(job.get("description", r["job_description"])),
            evidence=evidence,
            proposal=delimit_untrusted(r["proposal"], "PROPOSAL"),
        )
        out[r["item_id"]] = {**s.model_dump(), "usage": res.usage}
        JUDGED.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"  {r['item_id']} overall={s.overall} {s.reason[:80]}")


def cohen_kappa(a: list[int], b: list[int], weighted: bool) -> float | None:
    cats = [1, 2, 3, 4, 5]
    n = len(a)
    if n == 0:
        return None
    idx = {c: i for i, c in enumerate(cats)}
    obs = [[0.0] * 5 for _ in cats]
    for x, y in zip(a, b, strict=True):
        obs[idx[x]][idx[y]] += 1
    pa = [sum(obs[i]) / n for i in range(5)]
    pb = [sum(obs[i][j] for i in range(5)) / n for j in range(5)]

    def w(i: int, j: int) -> float:
        return ((i - j) ** 2) / 16 if weighted else (0.0 if i == j else 1.0)

    o = sum(w(i, j) * obs[i][j] / n for i in range(5) for j in range(5))
    e = sum(w(i, j) * pa[i] * pb[j] for i in range(5) for j in range(5))
    return round(1 - o / e, 3) if e else None


def kappa() -> None:
    rows = list(csv.DictReader(SHEET.open(encoding="utf-8")))
    judged = json.loads(JUDGED.read_text(encoding="utf-8"))
    res: dict[str, Any] = {}
    for c in CRITERIA:
        pairs = [
            (int(r[f"human_{c}"]), int(judged[r["item_id"]][c]))
            for r in rows
            if r.get(f"human_{c}", "").strip().isdigit() and r["item_id"] in judged
        ]
        h, j = [p[0] for p in pairs], [p[1] for p in pairs]
        res[c] = {
            "n": len(pairs),
            "kappa_quadratic": cohen_kappa(h, j, True),
            "kappa_unweighted": cohen_kappa(h, j, False),
            "exact_agreement": round(sum(1 for x, y in pairs if x == y) / len(pairs), 3)
            if pairs
            else None,
            "mean_human": round(sum(h) / len(h), 2) if h else None,
            "mean_judge": round(sum(j) / len(j), 2) if j else None,
        }
    path = write_result(
        "judge_calibration", {"criteria": res, "sheet": str(SHEET.relative_to(ROOT))}
    )
    print(json.dumps(res, indent=2))
    print(f"-> {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["export", "judge", "kappa"])
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args()
    if args.cmd == "export":
        export(args.n, args.seed)
    elif args.cmd == "judge":
        asyncio.run(judge_all())
    else:
        kappa()


if __name__ == "__main__":
    main()
