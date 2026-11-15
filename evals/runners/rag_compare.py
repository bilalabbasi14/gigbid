"""Per-query comparison of two retrieval variants: which jobs one wins or loses, and what kind of
evidence each puts in its top 5.

  uv run python -m evals.runners.rag_eval --variants v2_hybrid,v3_rerank --personas fullstack --rows --tag _fullstack
  uv run python -m evals.runners.rag_compare --a v2_hybrid --b v3_rerank --tag _fullstack

Writes evals/results/rag_compare_<a>_<b><tag>.json.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any

from evals.runners.harness import RESULTS, write_result


def load(variant: str, tag: str) -> dict[str, dict[str, Any]]:
    path = RESULTS / f"rag_{variant}{tag}_rows.jsonl"
    return {(r := json.loads(line))["job_id"]: r for line in path.open(encoding="utf-8")}


def top_types(row: dict[str, Any], k: int = 5) -> Counter[str]:
    return Counter(e["doc_type"] for e in row["ranked"][:k])


def gold_in_top(row: dict[str, Any], k: int = 5) -> list[str]:
    seen: list[str] = []
    for e in row["ranked"]:
        if e["project"] and e["project"] not in seen:
            seen.append(e["project"])
    return [p for p in seen[:k] if p in set(row["gold"])]


def compare(a: dict[str, dict[str, Any]], b: dict[str, dict[str, Any]]) -> dict[str, Any]:
    shared = sorted(set(a) & set(b))
    won, lost = [], []
    types_a, types_b = Counter(), Counter()
    types_b_on_losses: Counter[str] = Counter()
    for j in shared:
        ra, rb = a[j], b[j]
        types_a += top_types(ra)
        types_b += top_types(rb)
        delta = rb["recall@5"] - ra["recall@5"]
        if delta == 0:
            continue
        item = {
            "job_id": j,
            "title": ra.get("title"),
            "recall_a": ra["recall@5"],
            "recall_b": rb["recall@5"],
            "gold": ra["gold"],
            "gold_found_a": gold_in_top(ra),
            "gold_found_b": gold_in_top(rb),
            "top5_types_a": dict(top_types(ra)),
            "top5_types_b": dict(top_types(rb)),
        }
        (won if delta > 0 else lost).append(item)
        if delta < 0:
            types_b_on_losses += top_types(rb)
    n = len(shared) or 1
    return {
        "n_queries": len(shared),
        "b_better": len(won),
        "b_worse": len(lost),
        "unchanged": len(shared) - len(won) - len(lost),
        "top5_doc_type_share_a": {t: round(c / (5 * n), 3) for t, c in types_a.most_common()},
        "top5_doc_type_share_b": {t: round(c / (5 * n), 3) for t, c in types_b.most_common()},
        "top5_doc_types_of_b_on_its_losses": dict(types_b_on_losses.most_common()),
        "b_worse_jobs": lost,
        "b_better_jobs": won,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="v2_hybrid")
    ap.add_argument("--b", default="v3_rerank")
    ap.add_argument("--tag", default="_fullstack")
    args = ap.parse_args()
    res = compare(load(args.a, args.tag), load(args.b, args.tag))
    path = write_result(
        f"rag_compare_{args.a}_{args.b}{args.tag}", {"a": args.a, "b": args.b, **res}
    )
    print(
        f"{args.b} vs {args.a}: better on {res['b_better']}, worse on {res['b_worse']} of "
        f"{res['n_queries']}; top-5 types {res['top5_doc_type_share_a']} -> "
        f"{res['top5_doc_type_share_b']} -> {path}"
    )


if __name__ == "__main__":
    main()
