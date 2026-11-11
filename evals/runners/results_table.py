"""Build the results tables from committed result files and write them into README.md.

Every number in the README comes from evals/results/*.json through this script; README blocks
between `<!-- results: NAME -->` and `<!-- /results -->` are replaced, nothing else is touched.
Missing results render as "not yet run" rather than a number.

  uv run python -m evals.runners.results_table
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent.settings import ROOT

RES = ROOT / "evals/results"
README = ROOT / "README.md"
VARIANT_NAMES = {
    "v0_naive": "V0 naive dense",
    "v1_decompose": "V1 requirement decomposition",
    "v2_hybrid": "V2 hybrid BM25 + dense (RRF)",
    "v3_rerank": "V3 cross-encoder rerank",
    "v4_outcome": "V4 outcome-aware",
    "v5_multivector": "V5 multi-vector projects",
    "v6_contextual": "V6 contextual",
    "v7_hyde": "V7 HyDE",
    "v8_corrective": "V8 corrective loop",
    "v9_skill_graph": "V9 skill graph",
    "best": "Best pipeline",
}


def load(name: str) -> dict[str, Any] | None:
    p = RES / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def f(x: Any, digits: int = 3) -> str:
    if x is None:
        return "–"
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return str(x)


def rag_table() -> str:
    summary = load("rag_summary") or {}
    rows = [
        "| Variant | Evidence Recall@5 | MRR | nDCG@10 | Unsupported claims / proposal | Judge score | GigSim reply rate | p95 retrieval latency (s) | Cost / proposal (USD) | Source |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for v, label in VARIANT_NAMES.items():
        r = summary.get(v)
        if not r or not r.get("overall"):
            continue
        ov = r["overall"]
        p95 = (
            max((m.get("latency_p95_s") or 0) for m in r["personas"].values())
            if r.get("personas")
            else None
        )
        prop = load(f"proposal_eval_{v}") or {}
        po = prop.get("overall", {})
        judge = (load(f"judge_{v}") or {}).get("overall_mean")
        rows.append(
            f"| {label} | {f(ov.get('recall@5'))} | {f(ov.get('mrr'))} | {f(ov.get('ndcg@10'))} | {f(po.get('unsupported_claims_per_proposal_after'))} | {f(judge, 2)} | {f((po.get('gigsim') or {}).get('reply_rate'))} | {f(p95, 2)} | {f((po.get('cost_usd_per_proposal') or {}).get('mean'), 4)} | evals/results/rag_{v}.json |"
        )
    return "\n".join(rows) if len(rows) > 2 else "_Not yet run: `make eval-rag`._"


def persona_table() -> str:
    summary = load("rag_summary") or {}
    personas = ["ai_ml", "fullstack", "data_analyst"]
    rows = [
        "| Variant | " + " | ".join(f"{p} R@5" for p in personas) + " | Source |",
        "|---|" + "---|" * len(personas) + "---|",
    ]
    for v, label in VARIANT_NAMES.items():
        r = summary.get(v)
        if not r or not r.get("personas"):
            continue
        cells = [f(r["personas"].get(p, {}).get("recall@5")) for p in personas]
        rows.append(f"| {label} | " + " | ".join(cells) + " | evals/results/rag_summary.json |")
    return "\n".join(rows) if len(rows) > 2 else "_Not yet run._"


def decision_table() -> str:
    d = load("decision_eval")
    if not d:
        return "_Not yet run: `make eval-decisions`._"
    o = d["overall"]
    return "\n".join(
        [
            "| Metric | Value | Source |",
            "|---|---|---|",
            f"| Bid-or-skip F1 | {f(o['bid_skip']['f1'])} | evals/results/decision_eval.json |",
            f"| Scam precision / recall | {f(o['scam']['precision'])} / {f(o['scam']['recall'])} | evals/results/decision_eval.json |",
            f"| Injection posts flagged | {f(o.get('injection_detection_rate'))} | evals/results/decision_eval.json |",
            f"| Price inside the fair band | {f(o.get('price_in_fair_band'))} | evals/results/decision_eval.json |",
            f"| p50 / p95 latency per job analysed (s) | {f(o['latency_s_per_job']['p50'], 1)} / {f(o['latency_s_per_job']['p95'], 1)} | evals/results/decision_eval.json |",
            f"| Mean cost per job analysed (USD) | {f(o['cost_usd_per_job']['mean'], 5)} | evals/results/decision_eval.json |",
            f"| Jobs evaluated | {o['n']} | evals/results/decision_eval.json |",
        ]
    )


def multiagent_table() -> str:
    d = load("multiagent_comparison")
    if not d or not d.get("systems"):
        return "_Not yet run: `uv run python -m evals.runners.multiagent_compare`._"
    names = {
        "single": "(a) single ReAct agent",
        "supervisor": "(b) langgraph-supervisor",
        "graph": "(c) GigBid graph",
    }
    rows = [
        "| System | Jobs | Bid-or-skip accuracy | Scam recall | Unsupported claims / proposal | Violations left in output | Violations caught | GigSim reply rate | Tokens / job | p95 latency (s) | Source |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for k in ("single", "supervisor", "graph"):
        m = d["systems"].get(k)
        if not m:
            continue
        rows.append(
            f"| {names[k]} | {m['n']} | {f(m['bid_skip_accuracy'])} | {f(m['scam_recall'])} | {f(m['unsupported_claims_per_proposal'])} | {f(m['violations_in_output'])} | {f(m['violations_caught_by_guard'])} | {f(m['gigsim_reply_rate'])} | {f(m['tokens_per_job'])} | {f(m['latency_s']['p95'], 1)} | evals/results/multiagent_comparison.json |"
        )
    return "\n".join(rows)


def tool_table() -> str:
    d = load("tool_design")
    if not d:
        return "_Not yet run: `uv run python -m evals.runners.tool_design_eval`._"
    names = {
        "fine": "A. fine-grained (18 tools)",
        "coarse": "B. coarse (3 tools)",
        "best": "C. fine-grained, rewritten descriptions",
    }
    rows = [
        "| Tool set | Selection accuracy | Argument accuracy | Tokens / task | Source |",
        "|---|---|---|---|---|",
    ]
    for k, m in d["summary"].items():
        rows.append(
            f"| {names.get(k, k)} | {f(m['selection_accuracy'])} | {f(m['argument_accuracy'])} | {f(m['tokens_per_task'], 0)} | evals/results/tool_design.json |"
        )
    return "\n".join(rows)


def safety_table() -> str:
    inj = load("injection")
    x3 = load("x3_eval")
    rows = ["| Measure | Value | Source |", "|---|---|---|"]
    if inj:
        rows.append(
            f"| Injection attack success without / with defences | {f(inj['attack_success_rate_without_defences'])} / {f(inj['attack_success_rate_with_defences'])} (n={inj['n']}) | evals/results/injection.json |"
        )
        rows.append(
            f"| Proposals or messages sent without approval | {inj['sent_without_approval']} | evals/results/injection.json |"
        )
    if x3:
        o = x3["overall"]
        rw = o.get("retrieval_weighted", {})
        rows.append(
            f"| X3 builder: unsupported claims before / after verification | {f(o['unsupported_rate_before'])} / {f(o['unsupported_rate_after'])} | evals/results/x3_eval.json |"
        )
        rows.append(
            f"| X3 builder: library recall from code | {f(o['library_recall'])} | evals/results/x3_eval.json |"
        )
        if rw:
            rows.append(
                f"| X3 Recall@5 on repo projects: no case studies / builder / written | {f(rw.get('base', {}).get('recall@5'))} / {f(rw.get('built', {}).get('recall@5'))} / {f(rw.get('original', {}).get('recall@5'))} | evals/results/x3_eval.json |"
            )
    return "\n".join(rows) if len(rows) > 2 else "_Not yet run._"


BLOCKS = {
    "rag": rag_table,
    "rag_personas": persona_table,
    "decisions": decision_table,
    "multiagent": multiagent_table,
    "tools": tool_table,
    "safety": safety_table,
}


def main() -> None:
    out_md = []
    for name, fn in BLOCKS.items():
        out_md.append(f"## {name}\n\n{fn()}\n")
    (RES / "results_tables.md").write_text("\n".join(out_md), encoding="utf-8")
    text = README.read_text(encoding="utf-8")
    for name, fn in BLOCKS.items():
        pat = re.compile(rf"(<!-- results: {name} -->\n).*?(\n<!-- /results -->)", re.S)
        text = pat.sub(lambda m, fn=fn: m.group(1) + fn() + m.group(2), text)
    README.write_text(text, encoding="utf-8")
    print(f"wrote {RES / 'results_tables.md'} and updated README blocks: {', '.join(BLOCKS)}")


if __name__ == "__main__":
    main()
