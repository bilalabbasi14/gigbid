"""Claim verification (B3): split a draft into claims, check each against evidence, label it
supported / partly_supported / unsupported, and repair the draft before the Critic sees it.

Two signals per claim: the cross-encoder relevance between the claim and its cited evidence
(cheap, deterministic) and an LLM judgement over the cited + best-matching evidence. The LLM
decides; the reranker score is kept as a feature and used alone when the model is unavailable.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from agent import settings
from agent.handoffs import Claim, ClaimLabel
from agent.structured import LLMResult, call_prompt, call_structured

log = logging.getLogger(__name__)

CITE = re.compile(r"\[([0-9a-f]{8,32})\]")
CLAIM_HINT = re.compile(
    r"\b(I|we|my|our)\b.*\b(built|delivered|developed|designed|led|shipped|reduced|increased|improved|worked|experience|years|clients?|projects?|deployed|trained|implemented|migrated|cut|grew|achieved)\b",
    re.I,
)


class _Split(BaseModel):
    class Item(BaseModel):
        text: str
        cited_evidence_ids: list[str] = Field(default_factory=list)

    claims: list[Item] = Field(default_factory=list)


class _Labels(BaseModel):
    class Item(BaseModel):
        claim_id: str
        label: str
        best_evidence_id: str | None = None
        why: str = ""

    labels: list[Item] = Field(default_factory=list)


def split_claims_fallback(text: str) -> list[dict[str, Any]]:
    """Sentence-level heuristic split when the model is unavailable."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text)):
        if CLAIM_HINT.search(sent) or CITE.search(sent):
            out.append({"text": sent.strip(), "cited_evidence_ids": CITE.findall(sent)})
    return out[:15]


def _evidence_text(e: dict[str, Any]) -> str:
    return f"{e.get('title', '')}. {e.get('excerpt', '')}"


def rerank_support(claim: str, evidence: list[dict[str, Any]]) -> tuple[float, str | None]:
    if not evidence:
        return 0.0, None
    from rag.embeddings import rerank_scores

    scores = rerank_scores(
        re.sub(r"\[[0-9a-f]{8,32}\]", "", claim), [_evidence_text(e) for e in evidence]
    )
    best = max(range(len(scores)), key=lambda i: scores[i])
    return float(scores[best]), evidence[best]["evidence_id"]


def label_from_score(score: float, cfg: dict[str, float]) -> ClaimLabel:
    if score >= float(cfg.get("claim_support_min", 0.55)):
        return "supported"
    if score >= float(cfg.get("claim_partial_min", 0.35)):
        return "partly_supported"
    return "unsupported"


async def verify_claims(
    draft_text: str,
    evidence: list[dict[str, Any]],
    *,
    invoke: Callable[..., Awaitable[Any]] | None = None,
    use_reranker: bool = True,
) -> tuple[list[Claim], list[LLMResult]]:
    """Split + label. Returns claims and the LLM results (for usage accounting)."""
    cfg = settings.config().thresholds
    results: list[LLMResult] = []
    by_id = {e["evidence_id"]: e for e in evidence}
    try:
        split, res = await call_structured(
            "verifier", "verifier_split", _Split, invoke=invoke, proposal=draft_text
        )
        results.append(res)
        raw = [{"text": c.text, "cited_evidence_ids": c.cited_evidence_ids} for c in split.claims]
    except Exception:  # noqa: BLE001
        raw = split_claims_fallback(draft_text)
    claims: list[Claim] = []
    for i, c in enumerate(raw[:15]):
        cited = [x for x in c["cited_evidence_ids"] if x in by_id]
        pool = [by_id[x] for x in cited] or evidence
        score, best = (0.0, None)
        if use_reranker and pool:
            try:
                score, best = rerank_support(c["text"], pool)
            except Exception:  # noqa: BLE001
                score, best = (0.0, cited[0] if cited else None)
        claims.append(
            Claim(
                claim_id=f"c{i + 1}",
                text=c["text"],
                cited_evidence_ids=cited,
                support_score=round(score, 3),
                best_evidence_id=best or (cited[0] if cited else None),
                label=label_from_score(score, cfg)
                if use_reranker
                else ("supported" if cited else "unsupported"),
            )
        )

    if claims:
        block = []
        for cl in claims:
            ev_ids = cl.cited_evidence_ids or ([cl.best_evidence_id] if cl.best_evidence_id else [])
            ev_txt = (
                "\n".join(
                    f"    [{eid}] {_evidence_text(by_id[eid])[:500]}"
                    for eid in ev_ids
                    if eid in by_id
                )
                or "    (no evidence cited)"
            )
            block.append(f"Claim {cl.claim_id}: {cl.text}\n  Evidence:\n{ev_txt}")
        try:
            labels, res2 = await call_structured(
                "verifier",
                "verifier_judge",
                _Labels,
                invoke=invoke,
                claims_block="\n\n".join(block),
            )
            results.append(res2)
            by_claim = {lab.claim_id: lab for lab in labels.labels}
            for cl in claims:
                lab = by_claim.get(cl.claim_id)
                if lab and lab.label in ("supported", "partly_supported", "unsupported"):
                    # the model may not upgrade a claim that cites nothing and has no reranker support
                    if (
                        lab.label == "supported"
                        and not cl.cited_evidence_ids
                        and cl.support_score < float(cfg.get("claim_partial_min", 0.35))
                    ):
                        cl.label = "partly_supported"
                    else:
                        cl.label = lab.label  # type: ignore[assignment]
                    if lab.best_evidence_id in by_id:
                        cl.best_evidence_id = lab.best_evidence_id
        except Exception as exc:  # noqa: BLE001 - keep reranker labels
            log.warning("claim judge unavailable, keeping reranker labels: %s", exc)
    return claims, results


async def repair_draft(
    draft_text: str, claims: list[Claim], *, invoke: Callable[..., Awaitable[Any]] | None = None
) -> tuple[str, list[Claim], LLMResult | None]:
    flagged = [c for c in claims if c.label != "supported"]
    if not flagged:
        return draft_text, claims, None
    lines = "\n".join(
        f"- {c.claim_id} [{c.label}]: {c.text}"
        + (
            f" (best evidence [{c.best_evidence_id}])"
            if c.best_evidence_id
            else " (no evidence: remove)"
        )
        for c in flagged
    )
    try:
        res = await call_prompt(
            "verifier", "verifier_rewrite", invoke=invoke, proposal=draft_text, flagged=lines
        )
        new_text = res.text.strip() or draft_text
    except Exception:  # noqa: BLE001 - hard fallback: delete unsupported sentences
        new_text = draft_text
        for c in flagged:
            if c.label == "unsupported":
                new_text = new_text.replace(c.text, "")
        res = None
    for c in flagged:
        still_there = c.text[:60].lower() in new_text.lower()
        c.action = (
            "keep"
            if still_there and c.label == "partly_supported"
            else ("rewritten" if still_there else "removed")
        )  # type: ignore[assignment]
    return new_text, claims, res


def unsupported_rate(claims: list[Claim]) -> float:
    return (
        round(sum(1 for c in claims if c.label == "unsupported") / len(claims), 3)
        if claims
        else 0.0
    )
