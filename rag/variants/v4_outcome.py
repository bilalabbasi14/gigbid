"""V4 outcome-aware ranking: boost evidence that past winning or replied proposals cited, and the
phrasing of those proposals themselves. Learns from what actually worked.

Boost weights come from config (rag.outcome_boost). A chunk gets the boost of the best outcome
among proposals that cite its project; proposal chunks get their own outcome's boost."""

from __future__ import annotations

from typing import Any

from agent import settings
from rag.retriever import Resources, to_evidence
from rag.schema import Evidence
from rag.variants.v3_rerank import CrossEncoderRerank

ORDER = {"won": 3, "replied": 2, "ignored": 1}


class OutcomeAware:
    name = "v4_outcome"

    def __init__(self, resources: Resources, base: Any | None = None) -> None:
        self.res = resources
        self.base = base or CrossEncoderRerank(resources)
        self._outcomes: dict[str, dict[str, str]] = {}

    def project_outcomes(self, persona: str) -> dict[str, str]:
        """project_id -> best outcome among proposals citing it (cached per persona)."""
        if persona in self._outcomes:
            return self._outcomes[persona]
        best: dict[str, str] = {}
        for c in self.res.store.all_chunks(persona):
            if c.doc_type == "proposal" and c.outcome and c.project_id:
                if ORDER.get(c.outcome, 0) > ORDER.get(best.get(c.project_id, ""), 0):
                    best[c.project_id] = c.outcome
        self._outcomes[persona] = best
        return best

    def retrieve(
        self, job: dict[str, Any], persona: str, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        boost = settings.config().rag.get(
            "outcome_boost", {"won": 0.25, "replied": 0.1, "ignored": -0.05}
        )
        cands = self.base.retrieve(job, persona, k=max(k * 3, 12), filters=filters)
        outcomes = self.project_outcomes(persona)
        # normalise base scores to 0..1 so additive boosts are comparable across variants
        if cands:
            lo, hi = min(e.score for e in cands), max(e.score for e in cands)
            span = (hi - lo) or 1.0
        rescored = []
        for e in cands:
            base = (e.score - lo) / span if cands else 0.0
            oc = e.outcome if e.doc_type == "proposal" else outcomes.get(e.project_id or "")
            b = float(boost.get(oc, 0.0)) if oc else 0.0
            e.scores = {**e.scores, "base_norm": round(base, 4), "outcome_boost": b}
            e.score = round(base + b, 4)
            rescored.append(e)
        rescored.sort(key=lambda e: -e.score)
        return rescored[:k]


def _unused(_: Any) -> Any:  # keep to_evidence import for type checkers
    return to_evidence
