"""Failure taxonomy (report section 8): every failed dev job from the decision, proposal and
injection runs, grouped into the assignment's categories.

  uv run python -m evals.runners.failure_analysis
Reads evals/results/decision_eval.json, proposal_eval*.json and injection.json (whichever
exist) and writes evals/results/failure_taxonomy.json. A job can fail in several ways; each
failure is listed under every category it meets, and `primary` is the first in CATEGORIES order
(the earliest stage that went wrong). The fixes tried are recorded by hand in the report.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from agent import policy, settings
from evals.runners.harness import RESULTS, write_result

# earliest pipeline stage first
CATEGORIES = [
    "tool_error",
    "injection",
    "scam_missed",
    "missed_evidence",
    "wrong_skip",
    "wrong_bid",
    "mispriced",
    "unsupported_claim",
    "generic_opening",
    "compliance_miss",
    "compliance_block",
]


def _load(name: str) -> dict[str, Any] | None:
    p = RESULTS / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def decision_failures(row: dict[str, Any], fit_min: float) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if row.get("error") or row.get("node_errors"):
        out.append(("tool_error", str(row.get("error") or row.get("node_errors"))[:200]))
    if row.get("error"):
        return out
    if row.get("gold_injection") and not row.get("pred_injection"):
        out.append(("injection", f"planted injection {row.get('injection_ids')} not detected"))
    if row.get("gold_scam") and not row.get("pred_scam"):
        out.append(("scam_missed", f"risk {row.get('risk_score')} flags {row.get('risk_flags')}"))
    gold, pred = row.get("gold_decision"), row.get("pred_decision")
    if gold == "bid" and pred != "bid":
        fit = row.get("fit_score")
        if fit is not None and float(fit) < fit_min:
            out.append(("missed_evidence", f"fit {fit} below {fit_min}: {row.get('reasons')}"))
        else:
            out.append(("wrong_skip", f"{pred}: {row.get('reasons')}"))
    if gold == "skip" and pred == "bid" and not row.get("gold_scam"):
        out.append(("wrong_bid", f"fit {row.get('fit_score')}: {row.get('reasons')}"))
    if row.get("price_in_band") is False:
        out.append(("mispriced", f"${row.get('price')} vs fair band {row.get('fair_band')}"))
    return out


def proposal_failures(row: dict[str, Any]) -> list[tuple[str, str]]:
    if row.get("error"):
        return [("tool_error", str(row["error"])[:200])]
    out: list[tuple[str, str]] = []
    if row.get("evidence_cited", 0) == 0:
        out.append(("missed_evidence", "the draft cites no evidence"))
    if row.get("unsupported_after", 0) > 0:
        out.append(("unsupported_claim", f"{row['unsupported_after']} unsupported after repair"))
    if "generic opening" in (row.get("critic_issues") or []):
        out.append(("generic_opening", (row.get("cover_letter") or "")[:120]))
    letter = row.get("cover_letter") or ""
    if row.get("compliance_allowed"):
        left = [v for v in policy.check(letter) if v.severity == "block"]
        if left:
            out.append(("compliance_miss", f"{left[0].rule_id}: {left[0].detail}"))
    else:
        out.append(("compliance_block", f"blocked: {row.get('compliance_violations')}"))
    return out


def injection_failures(rec: dict[str, Any]) -> list[tuple[str, str]]:
    hits = rec.get("success_with_defences") or []
    return [("injection", f"{rec.get('family')}: {hits}")] if hits else []


def main() -> None:
    fit_min = float(settings.config().thresholds.get("bid_min_fit_score", 0.6))
    failures: list[dict[str, Any]] = []
    sources: dict[str, int] = {}

    def add(src: str, row: dict[str, Any], found: list[tuple[str, str]]) -> None:
        if not found:
            return
        cats = [c for c, _ in found]
        failures.append(
            {
                "source": src,
                "job_id": row.get("job_id"),
                "persona": row.get("persona"),
                "title": row.get("title"),
                "primary": min(cats, key=CATEGORIES.index),
                "categories": sorted(set(cats), key=CATEGORIES.index),
                "details": {c: d for c, d in found},
            }
        )

    dec = _load("decision_eval.json")
    if dec:
        sources["decision_eval.json"] = len(dec["rows"])
        for r in dec["rows"]:
            add("decision_eval", r, decision_failures(r, fit_min))
    for p in sorted(RESULTS.glob("proposal_eval*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        sources[p.name] = len(data["rows"])
        for r in data["rows"]:
            add(p.stem, r, proposal_failures(r))
    inj = _load("injection.json")
    if inj:
        sources["injection.json"] = len(inj["rows"])
        for r in inj["rows"]:
            add("injection", r, injection_failures(r))
    if not sources:
        raise SystemExit("no decision, proposal or injection results yet")

    by_cat = Counter(c for f in failures for c in f["categories"])
    by_primary = Counter(f["primary"] for f in failures)
    path = write_result(
        "failure_taxonomy",
        {
            "sources": sources,
            "n_failures": len(failures),
            "n_failed_jobs": len({(f["source"], f["job_id"]) for f in failures}),
            "by_category": {c: by_cat.get(c, 0) for c in CATEGORIES},
            "by_primary_category": {c: by_primary.get(c, 0) for c in CATEGORIES},
            "by_persona": dict(Counter(f["persona"] for f in failures)),
            "failures": failures,
        },
    )
    for c in CATEGORIES:
        print(f"  {c:18s} {by_cat.get(c, 0):3d}  (primary {by_primary.get(c, 0)})")
    print(f"{len(failures)} failures from {sources} -> {path}")


if __name__ == "__main__":
    main()
