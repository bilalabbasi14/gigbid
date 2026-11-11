"""Claim verification repair step without models (fallback paths)."""

from __future__ import annotations

import pytest

from agent.handoffs import Claim, ProposalDraft
from rag.verify import label_from_score, repair_draft, split_claims_fallback, unsupported_rate


async def _fail(*a, **k):
    raise RuntimeError("model unavailable")


async def test_repair_keeps_partly_supported_claims_with_valid_action():
    text = "I built a RAG bot with 94% accuracy [aaaa1111bbbb2222]. I have 10 years of Rust experience."
    claims = [
        Claim(
            claim_id="c1",
            text="I built a RAG bot with 94% accuracy",
            cited_evidence_ids=["aaaa1111bbbb2222"],
            label="partly_supported",
            support_score=0.4,
        ),
        Claim(
            claim_id="c2",
            text="I have 10 years of Rust experience.",
            label="unsupported",
            support_score=0.0,
        ),
    ]
    new_text, out, res = await repair_draft(text, claims, invoke=_fail)
    assert res is None and "Rust" not in new_text  # hard fallback deletes unsupported sentences
    actions = {c.claim_id: c.action for c in out}
    assert actions == {"c1": "keep", "c2": "removed"}
    # the repaired claims must round-trip through the hand-off model (regression: "kept" was invalid)
    ProposalDraft(job_id="j", cover_letter=new_text, claims=[c.model_dump() for c in out])
    assert unsupported_rate([c for c in out if c.action != "removed"]) == 0.0


def test_fallback_split_and_thresholds():
    claims = split_claims_fallback(
        "You need a dashboard. I built three Power BI dashboards for retailers [abcd1234abcd1234]. Happy to start Monday."
    )
    assert len(claims) == 1 and claims[0]["cited_evidence_ids"] == ["abcd1234abcd1234"]
    cfg = {"claim_support_min": 0.55, "claim_partial_min": 0.35}
    assert [label_from_score(x, cfg) for x in (0.9, 0.4, 0.1)] == [
        "supported",
        "partly_supported",
        "unsupported",
    ]


@pytest.mark.parametrize("rate_input,expected", [([], 0.0)])
def test_unsupported_rate_empty(rate_input, expected):
    assert unsupported_rate(rate_input) == expected
