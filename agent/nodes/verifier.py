"""Verifier node: claim verification before the Critic. Reports unsupported-claim rate before and
after repair and rewrites the draft."""

from __future__ import annotations

from typing import Any

from agent.deps import Deps
from agent.handoffs import ProposalDraft
from agent.nodes._common import llm_event, node_output, obs
from agent.nodes.writer import parse_draft
from agent.state import BidState, TraceEvent
from rag.verify import repair_draft, unsupported_rate, verify_claims

NODE = "verifier"


def _full_text(d: dict[str, Any]) -> str:
    answers = "\n".join(f"Q{i + 1}: {a}" for i, a in enumerate(d.get("screening_answers", [])))
    return f"<cover_letter>\n{d.get('cover_letter', '')}\n</cover_letter>\n<answers>\n{answers}\n</answers>"


async def run(state: BidState, deps: Deps) -> dict[str, Any]:
    use_reranker = deps.use_reranker
    events: list[TraceEvent] = []
    draft = dict(state["proposal_draft"])
    evidence = state.get("evidence", [])
    usage: dict[str, int] = {}
    text = _full_text(draft)
    claims, results = await verify_claims(
        text, evidence, invoke=deps.invoke, use_reranker=use_reranker
    )
    for r in results:
        events.append(llm_event(NODE, "verifier", r))
        usage = {k: usage.get(k, 0) + v for k, v in r.usage.items()}
    before = unsupported_rate(claims)
    counts_before = {
        lab: sum(1 for c in claims if c.label == lab)
        for lab in ("supported", "partly_supported", "unsupported")
    }
    new_text, claims, res = await repair_draft(text, claims, invoke=deps.invoke)
    if res:
        events.append(llm_event(NODE, "verifier_rewrite", res))
        usage = {k: usage.get(k, 0) + v for k, v in res.usage.items()}
    # re-label after repair: removed claims no longer count; rewritten ones are treated as partly supported
    after_claims = [c for c in claims if c.action != "removed"]
    for c in after_claims:
        if c.action == "rewritten" and c.label == "unsupported":
            c.label = "partly_supported"
    after = unsupported_rate(after_claims)
    cover, answers = parse_draft(new_text)
    pd = ProposalDraft.model_validate(
        {
            **draft,
            "cover_letter": cover or draft["cover_letter"],
            "screening_answers": answers or draft.get("screening_answers", []),
            "word_count": len((cover or draft["cover_letter"]).split()),
            "claims": [c.model_dump() for c in claims],
            "verification": {
                "claims": len(claims),
                "before": counts_before,
                "unsupported_rate_before": before,
                "unsupported_rate_after": after,
                "removed": sum(1 for c in claims if c.action == "removed"),
                "rewritten": sum(1 for c in claims if c.action == "rewritten"),
            },
        }
    )
    events.append(obs(NODE, "claims verified", **pd.verification))
    return node_output(NODE, "critiquing", events, usage, proposal_draft=pd.model_dump())
