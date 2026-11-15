"""Blind pairwise human panel (B4): classmates compare anonymised proposals for the same job.

1. Export pairs from two proposal runs (order randomised per pair, variant names hidden):
     uv run python -m evals.runners.blind_panel export --a proposal_eval_v0_naive --b proposal_eval_best --n 15
   -> evals/labeling/panel_sheet.csv   (give this to each rater; one copy per rater)
   -> data/processed/panel_key.json    (which variant is "1" and "2"; git-ignored until scoring)
2. Each rater fills `preferred` with 1, 2 or tie, and their name in `rater`. Save the copies as
   evals/labeling/panel_<rater>.csv.
3. Score:
     uv run python -m evals.runners.blind_panel score
   -> evals/results/blind_panel.json (win rate of B over A, a two-sided sign test, agreement
      between raters, and the de-blinded votes)
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter
from math import comb
from typing import Any

from agent.settings import ROOT
from evals.runners.harness import RESULTS, load_dev, write_result

LABELS = ROOT / "evals/labeling"
SHEET = LABELS / "panel_sheet.csv"
KEY = ROOT / "data/processed/panel_key.json"
FIELDS = [
    "pair_id",
    "job_title",
    "job_description",
    "proposal_1",
    "proposal_2",
    "preferred",
    "rater",
    "notes",
]


def _letters(name: str) -> dict[str, str]:
    data = json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))
    return {r["job_id"]: r["cover_letter"] for r in data["rows"] if r.get("cover_letter")}


def export(a: str, b: str, n: int, seed: int) -> None:
    la, lb = _letters(a), _letters(b)
    jobs = {
        r["job_id"]: r["job"] for p in ("ai_ml", "fullstack", "data_analyst") for r in load_dev(p)
    }
    shared = sorted(set(la) & set(lb) & set(jobs))
    rng = random.Random(seed)
    rng.shuffle(shared)
    key: dict[str, dict[str, str]] = {}
    LABELS.mkdir(parents=True, exist_ok=True)
    with SHEET.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for i, job_id in enumerate(shared[:n], 1):
            first_is_a = rng.random() < 0.5
            p1, p2 = (la[job_id], lb[job_id]) if first_is_a else (lb[job_id], la[job_id])
            pid = f"p{i:02d}"
            key[pid] = {"job_id": job_id, "1": a if first_is_a else b, "2": b if first_is_a else a}
            job = jobs[job_id]
            w.writerow(
                [pid, job["title"], (job.get("description") or "")[:1200], p1, p2, "", "", ""]
            )
    KEY.parent.mkdir(parents=True, exist_ok=True)
    KEY.write_text(
        json.dumps({"a": a, "b": b, "seed": seed, "pairs": key}, indent=2), encoding="utf-8"
    )
    print(f"wrote {len(key)} pairs to {SHEET}; the key is in {KEY} (do not share it with raters)")


def sign_test(wins: int, losses: int) -> float | None:
    """Two-sided exact binomial test of wins vs losses under p = 0.5 (ties dropped)."""
    n = wins + losses
    if n == 0:
        return None
    k = min(wins, losses)
    p = sum(comb(n, i) for i in range(k + 1)) / 2**n
    return round(min(1.0, 2 * p), 4)


def fleiss_kappa(votes_per_item: list[list[str]], cats: tuple[str, ...]) -> float | None:
    """Fleiss' kappa over items rated by the same number of raters (None if fewer than 2)."""
    items = [v for v in votes_per_item if len(v) >= 2]
    if not items or len({len(v) for v in items}) != 1:
        return None
    m = len(items[0])
    counts = [Counter(v) for v in items]
    p_j = [sum(c[cat] for c in counts) / (len(items) * m) for cat in cats]
    p_i = [(sum(c[cat] ** 2 for cat in cats) - m) / (m * (m - 1)) for c in counts]
    p_bar, p_e = sum(p_i) / len(p_i), sum(x * x for x in p_j)
    return round((p_bar - p_e) / (1 - p_e), 3) if p_e < 1 else None


def score() -> None:
    key = json.loads(KEY.read_text(encoding="utf-8"))
    a, b = key["a"], key["b"]
    votes: list[dict[str, Any]] = []
    for sheet in sorted(LABELS.glob("panel_*.csv")):
        if sheet == SHEET:
            continue
        for r in csv.DictReader(sheet.open(encoding="utf-8")):
            pref = (r.get("preferred") or "").strip().lower()
            if pref not in ("1", "2", "tie") or r["pair_id"] not in key["pairs"]:
                continue
            winner = "tie" if pref == "tie" else key["pairs"][r["pair_id"]][pref]
            votes.append(
                {
                    "pair_id": r["pair_id"],
                    "job_id": key["pairs"][r["pair_id"]]["job_id"],
                    "rater": (r.get("rater") or sheet.stem.removeprefix("panel_")).strip(),
                    "winner": winner,
                }
            )
    if not votes:
        raise SystemExit("no filled panel sheets (evals/labeling/panel_<rater>.csv) found")
    wins = sum(1 for v in votes if v["winner"] == b)
    losses = sum(1 for v in votes if v["winner"] == a)
    ties = sum(1 for v in votes if v["winner"] == "tie")
    by_pair: dict[str, list[str]] = {}
    for v in votes:
        by_pair.setdefault(v["pair_id"], []).append(
            "b" if v["winner"] == b else "a" if v["winner"] == a else "tie"
        )
    path = write_result(
        "blind_panel",
        {
            "a": a,
            "b": b,
            "raters": sorted({v["rater"] for v in votes}),
            "pairs": len(by_pair),
            "votes": len(votes),
            "b_wins": wins,
            "a_wins": losses,
            "ties": ties,
            "b_win_rate_excluding_ties": round(wins / (wins + losses), 3)
            if wins + losses
            else None,
            "sign_test_p_two_sided": sign_test(wins, losses),
            "fleiss_kappa": fleiss_kappa(list(by_pair.values()), ("a", "b", "tie")),
            "key": key["pairs"],
            "rows": votes,
        },
    )
    print(f"{b} preferred in {wins}, {a} in {losses}, ties {ties} -> {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["export", "score"])
    ap.add_argument(
        "--a", default="proposal_eval_v0_naive", help="baseline results file (no .json)"
    )
    ap.add_argument("--b", default="proposal_eval_best", help="candidate results file")
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args()
    if args.cmd == "export":
        export(args.a, args.b, args.n, args.seed)
    else:
        score()


if __name__ == "__main__":
    main()
