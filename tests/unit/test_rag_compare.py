"""Per-query retrieval comparison."""

from __future__ import annotations

from evals.runners.rag_compare import compare


def row(job: str, recall: float, types: list[str], projects: list[str]) -> dict:
    return {
        "job_id": job,
        "title": job,
        "gold": ["p1"],
        "recall@5": recall,
        "ranked": [
            {"project": p, "doc_type": t, "score": 1.0}
            for p, t in zip(projects, types, strict=True)
        ],
    }


def test_counts_wins_losses_and_doc_types() -> None:
    a = {
        "j1": row("j1", 1.0, ["case_study"] * 5, ["p1", "p2", "p3", "p4", "p5"]),
        "j2": row("j2", 0.0, ["case_study"] * 5, ["p2", "p3", "p4", "p5", "p6"]),
        "j3": row("j3", 1.0, ["review"] * 5, ["p1", "p2", "p3", "p4", "p5"]),
    }
    b = {
        "j1": row("j1", 0.0, ["code"] * 5, ["p2", "p3", "p4", "p5", "p6"]),
        "j2": row("j2", 1.0, ["case_study"] * 5, ["p1", "p3", "p4", "p5", "p6"]),
        "j3": row("j3", 1.0, ["review"] * 5, ["p1", "p2", "p3", "p4", "p5"]),
    }
    res = compare(a, b)
    assert (res["b_better"], res["b_worse"], res["unchanged"]) == (1, 1, 1)
    assert res["top5_doc_types_of_b_on_its_losses"] == {"code": 5}
    assert res["b_worse_jobs"][0]["gold_found_a"] == ["p1"]
    assert res["b_worse_jobs"][0]["gold_found_b"] == []
