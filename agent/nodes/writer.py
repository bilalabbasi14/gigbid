"""Proposal Writer: evidence-cited cover letter and screening answers. Reads the Critic's
revision instructions on later rounds. Only evidence in state (from the Fit Matcher, plus any
extra search) may be cited."""

from __future__ import annotations

import re
from typing import Any

from agent.deps import Deps
from agent.handoffs import ProposalDraft
from agent.nodes._common import job_text, llm_event, node_output
from agent.state import BidState
from agent.structured import call_prompt

NODE = "writer"


def parse_draft(text: str) -> tuple[str, list[str]]:
    cl = re.search(r"<cover_letter>(.*?)</cover_letter>", text, re.S)
    an = re.search(r"<answers>(.*?)</answers>", text, re.S)
    cover = (cl.group(1) if cl else text).strip()
    answers: list[str] = []
    if an:
        for part in re.split(r"^\s*Q\d+\s*:\s*", an.group(1).strip(), flags=re.M):
            if part.strip():
                answers.append(part.strip())
    return cover, answers


def evidence_block(evidence: list[dict[str, Any]]) -> str:
    return (
        "\n\n".join(
            f"[{e['evidence_id']}] ({e.get('type')}, {e.get('year')}) {e.get('title')}\n{(e.get('excerpt') or '')[:600]}"
            for e in evidence
        )
        or "(no evidence available: make no experience claims)"
    )


async def run(state: BidState, deps: Deps) -> dict[str, Any]:
    job, spec = state["job"], state.get("job_spec", {})
    evidence = state.get("evidence", [])
    price = state.get("price_quote", {})
    critique = state.get("critique") or {}
    revision = int(state.get("revision_count", 0))
    revision_block = ""
    if critique and not critique.get("passed", True) and critique.get("revision_instructions"):
        revision_block = f"This is revision {revision}. The Critic rejected the previous draft:\n{critique['revision_instructions']}\nIssues: {'; '.join(critique.get('issues', []))}\nPrevious draft:\n{state.get('proposal_draft', {}).get('cover_letter', '')}"
    res = await call_prompt(
        NODE,
        "writer",
        invoke=deps.invoke,
        title=job.get("title", ""),
        job_text=job_text(job),
        spec_summary=spec.get("summary", ""),
        deliverables="; ".join(spec.get("deliverables", [])) or "see post",
        hidden_needs="; ".join(spec.get("hidden_needs", [])) or "none identified",
        bid=f"${price.get('amount', 0):g} {price.get('bid_type', '')}",
        evidence=evidence_block(evidence),
        questions="\n".join(
            f"Q{i + 1}: {q}"
            for i, q in enumerate(
                spec.get("screening_questions") or job.get("screening_questions") or []
            )
        )
        or "(none)",
        style_rules="; ".join(state.get("style_rules", [])) or "none",
        outcome_hints="; ".join(state.get("outcome_hints", [])) or "none",
        revision_block=revision_block,
    )
    cover, answers = parse_draft(res.text)
    cited = sorted(set(re.findall(r"\[([0-9a-f]{8,32})\]", cover + " " + " ".join(answers))))
    known = {e["evidence_id"] for e in evidence}
    draft = ProposalDraft(
        job_id=job.get("job_id", ""),
        cover_letter=cover,
        screening_answers=answers,
        evidence_ids=[c for c in cited if c in known],
        revision=revision,
        word_count=len(cover.split()),
    )
    return node_output(
        NODE,
        "verifying",
        [llm_event(NODE, "writer", res, note=f"revision {revision}")],
        res.usage,
        proposal_draft=draft.model_dump(),
    )
