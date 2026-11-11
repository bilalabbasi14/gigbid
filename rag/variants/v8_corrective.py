"""V8 corrective RAG loop (LangGraph subgraph): retrieve -> grade evidence -> if weak, rewrite the
query and retrieve again (bounded) -> if still weak, return an explicit "no evidence" marker so
the writer refuses to claim. Grading is the cross-encoder relevance (deterministic), with the
threshold and max rounds in config."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agent import settings
from rag import embeddings
from rag.retriever import Resources, job_query_text
from rag.schema import Evidence
from rag.variants.v3_rerank import CrossEncoderRerank


class CRAGState(TypedDict, total=False):
    job: dict[str, Any]
    persona: str
    k: int
    filters: dict[str, Any] | None
    query_text: str
    round: int
    evidence: list[Evidence]
    grade: float
    weak: bool
    refused: bool
    log: Annotated[list[str], operator.add]


class CorrectiveRAG:
    name = "v8_corrective"

    def __init__(
        self,
        resources: Resources,
        base: Any | None = None,
        min_grade: float = 0.35,
        max_rounds: int = 2,
    ) -> None:
        self.res = resources
        self.base = base or CrossEncoderRerank(resources)
        self.min_grade = float(settings.config().rag.get("crag_min_grade", min_grade))
        self.max_rounds = int(settings.config().rag.get("crag_max_rounds", max_rounds))
        self.graph = self._build()

    # ---- nodes ----
    def _retrieve(self, s: CRAGState) -> dict[str, Any]:
        job = {**s["job"], "description": s.get("query_text") or s["job"].get("description", "")}
        ev = self.base.retrieve(job, s["persona"], k=s.get("k", 5), filters=s.get("filters"))
        return {"evidence": ev, "log": [f"round {s.get('round', 0)}: retrieved {len(ev)}"]}

    def _grade(self, s: CRAGState) -> dict[str, Any]:
        ev = s.get("evidence", [])
        if not ev:
            return {"grade": 0.0, "weak": True, "log": ["grade: no evidence"]}
        query = job_query_text(s["job"])[:2000]
        scores = embeddings.rerank_scores(query, [f"{e.title}. {e.excerpt}" for e in ev[:5]])
        top = max(scores) if scores else 0.0
        # keep only items that individually clear a lower bar; drop clearly irrelevant ones
        keep = [e for e, sc in zip(ev, scores, strict=False) if sc >= self.min_grade * 0.5] + ev[
            len(scores) :
        ]
        return {
            "grade": round(float(top), 4),
            "weak": top < self.min_grade,
            "evidence": keep,
            "log": [f"grade: top={top:.3f} weak={top < self.min_grade}"],
        }

    def _rewrite(self, s: CRAGState) -> dict[str, Any]:
        """Query rewrite without an LLM: focus on title + listed skills + requirement-like phrases."""
        job = s["job"]
        skills = ", ".join(job.get("skills") or [])
        title = job.get("title", "")
        desc = job.get("description", "")
        import re

        phrases = re.findall(
            r"(?:build|develop|create|implement|design|migrate|integrate|analy[sz]e|automate|deploy)[^.;\n]{10,80}",
            desc,
            re.I,
        )[:4]
        new_q = f"{title}. Skills: {skills}. " + " ".join(phrases)
        return {
            "query_text": new_q,
            "round": int(s.get("round", 0)) + 1,
            "log": [f"rewrite -> {new_q[:80]!r}"],
        }

    def _refuse(self, s: CRAGState) -> dict[str, Any]:
        return {
            "refused": True,
            "evidence": [],
            "log": ["refuse: no adequate evidence; writer must not claim experience"],
        }

    def _route(self, s: CRAGState) -> str:
        if not s.get("weak"):
            return END
        if int(s.get("round", 0)) < self.max_rounds:
            return "rewrite"
        return "refuse"

    def _build(self):  # type: ignore[no-untyped-def]
        g = StateGraph(CRAGState)
        g.add_node("retrieve", self._retrieve)
        g.add_node("grade", self._grade)
        g.add_node("rewrite", self._rewrite)
        g.add_node("refuse", self._refuse)
        g.add_edge(START, "retrieve")
        g.add_edge("retrieve", "grade")
        g.add_conditional_edges(
            "grade", self._route, {"rewrite": "rewrite", "refuse": "refuse", END: END}
        )
        g.add_edge("rewrite", "retrieve")
        g.add_edge("refuse", END)
        return g.compile()

    def retrieve(
        self, job: dict[str, Any], persona: str, k: int = 5, filters: dict[str, Any] | None = None
    ) -> list[Evidence]:
        out = self.graph.invoke(
            {"job": job, "persona": persona, "k": k, "filters": filters, "round": 0, "log": []}
        )
        ev = list(out.get("evidence", []))
        for e in ev:
            e.scores = {
                **e.scores,
                "crag_grade": out.get("grade", 0.0),
                "crag_rounds": out.get("round", 0),
            }
        return ev

    def retrieve_with_log(
        self, job: dict[str, Any], persona: str, k: int = 5
    ) -> tuple[list[Evidence], dict[str, Any]]:
        out = self.graph.invoke({"job": job, "persona": persona, "k": k, "round": 0, "log": []})
        return list(out.get("evidence", [])), {
            "grade": out.get("grade"),
            "rounds": out.get("round"),
            "refused": bool(out.get("refused")),
            "log": out.get("log", []),
        }
