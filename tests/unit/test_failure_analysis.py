"""Failure taxonomy classification on hand-made rows."""

from __future__ import annotations

from evals.runners import failure_analysis as fa


def test_decision_failures_follow_the_pipeline_order() -> None:
    row = {
        "gold_decision": "bid",
        "pred_decision": "skip",
        "fit_score": 0.3,
        "reasons": ["low fit"],
        "gold_scam": False,
        "gold_injection": True,
        "pred_injection": False,
        "injection_ids": ["ignore_previous"],
        "price_in_band": False,
        "price": 900,
        "fair_band": {"low": 100, "high": 300},
    }
    cats = [c for c, _ in fa.decision_failures(row, 0.6)]
    assert cats == ["injection", "missed_evidence", "mispriced"]
    assert min(cats, key=fa.CATEGORIES.index) == "injection"


def test_wrong_skip_when_fit_was_enough() -> None:
    row = {"gold_decision": "bid", "pred_decision": "skip", "fit_score": 0.8, "reasons": ["risk"]}
    assert [c for c, _ in fa.decision_failures(row, 0.6)] == ["wrong_skip"]


def test_errors_are_tool_errors_only() -> None:
    assert [c for c, _ in fa.decision_failures({"error": "Timeout"}, 0.6)] == ["tool_error"]


def test_proposal_failures() -> None:
    row = {
        "evidence_cited": 0,
        "unsupported_after": 2,
        "critic_issues": ["generic opening"],
        "compliance_allowed": True,
        "cover_letter": "I am passionate. Email me at a@b.co",
    }
    cats = [c for c, _ in fa.proposal_failures(row)]
    assert cats == ["missed_evidence", "unsupported_claim", "generic_opening", "compliance_miss"]
    blocked = {"evidence_cited": 3, "compliance_allowed": False, "compliance_violations": ["x"]}
    assert [c for c, _ in fa.proposal_failures(blocked)] == ["compliance_block"]


def test_clean_rows_are_not_failures() -> None:
    ok = {"gold_decision": "bid", "pred_decision": "bid", "fit_score": 0.8, "price_in_band": True}
    assert fa.decision_failures(ok, 0.6) == []
    good = {
        "evidence_cited": 3,
        "unsupported_after": 0,
        "critic_issues": [],
        "compliance_allowed": True,
        "cover_letter": "Your ETL needs...",
    }
    assert fa.proposal_failures(good) == []
