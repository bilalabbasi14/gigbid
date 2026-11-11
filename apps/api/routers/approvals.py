from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent import llm
from agent.guardrails import SYSTEM_GUARD
from agent.handoffs import ApprovalPayload
from agent.nodes.writer import evidence_block
from agent.prompts import load_prompt
from apps.api.auth.security import CurrentUser
from apps.api.db import Run, get_session
from apps.api.runtime import runtime
from apps.api.schemas import (
    ApprovalDecisionIn,
    ApprovalItem,
    ApprovalListOut,
    ApprovalResultOut,
    MessageApprovalPayload,
    PortfolioBuildPayload,
    RegenerateIn,
    RegenerateOut,
)

router = APIRouter(tags=["approvals"])


def to_item(r: Run, payload: dict) -> ApprovalItem:
    """Typed approval item: the bid graph's ApprovalPayload or the conversation graph's payload."""
    if r.kind == "portfolio":
        pf = PortfolioBuildPayload.model_validate(payload)
        title = f"Portfolio builder: {len(pf.drafts)} case studies from {pf.owner}"
        return ApprovalItem(
            thread_id=r.thread_id,
            kind="portfolio",
            job_id=None,
            title=title,
            created_at=r.updated_at,
            portfolio=pf,
        )
    if r.kind == "conversation":
        msg = MessageApprovalPayload.model_validate(payload)
        title = (msg.job or {}).get("title") or r.job_id or r.thread_id
        return ApprovalItem(
            thread_id=r.thread_id,
            kind="message",
            job_id=r.job_id,
            title=title,
            created_at=r.updated_at,
            message=msg,
        )
    prop = ApprovalPayload.model_validate(payload)
    title = (prop.job_spec.title if prop.job_spec else None) or r.job_id or r.thread_id
    return ApprovalItem(
        thread_id=r.thread_id,
        kind="proposal",
        job_id=r.job_id,
        title=title,
        created_at=r.updated_at,
        proposal=prop,
    )


@router.get("/approvals", response_model=ApprovalListOut)
async def pending(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> ApprovalListOut:
    runs = (
        await session.scalars(
            select(Run)
            .where(Run.user_id == user.user_id, Run.status == "awaiting_approval")
            .order_by(Run.updated_at.desc())
        )
    ).all()
    items = []
    for r in runs:
        payload = await runtime().pending_payload(r.thread_id, r.kind, user.user_id)
        if not payload:
            continue
        items.append(to_item(r, payload))
    return ApprovalListOut(items=items)


@router.get("/approvals/{thread_id}", response_model=ApprovalItem)
async def one(
    thread_id: str, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> ApprovalItem:
    r = await session.get(Run, thread_id)
    if r is None or r.user_id != user.user_id:
        raise HTTPException(404, "run not found")
    payload = await runtime().pending_payload(thread_id, r.kind, user.user_id)
    if not payload:
        raise HTTPException(409, f"run is not awaiting approval (status {r.status})")
    return to_item(r, payload)


@router.post("/approvals/{thread_id}", response_model=ApprovalResultOut)
async def decide(thread_id: str, body: ApprovalDecisionIn, user: CurrentUser) -> ApprovalResultOut:
    """Resume the interrupted graph with the human's decision. Approve submits (idempotently),
    edit re-checks compliance and may interrupt again, reject ends the thread."""
    decision = body.model_dump(exclude_none=True)
    decision["user_id"] = user.user_id
    try:
        values = await runtime().resume(thread_id, user.user_id, decision)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    next_item = None
    if values.get("status") == "awaiting_approval":
        async for s in get_session():
            r = await s.get(Run, thread_id)
        if r is not None:
            nxt = await runtime().pending_payload(thread_id, r.kind, user.user_id)
            next_item = to_item(r, nxt) if nxt else None
    return ApprovalResultOut(
        thread_id=thread_id,
        status=values.get("status", "unknown"),
        submission=values.get("submission"),
        sent=values.get("sent"),
        promoted_style_rules=values.get("_promoted_style_rules", []),
        next_proposal=next_item.proposal if next_item else None,
        next_message=next_item.message if next_item else None,
    )


@router.post("/proposals/{thread_id}/regenerate", response_model=RegenerateOut)
async def regenerate_paragraph(
    thread_id: str,
    body: RegenerateIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RegenerateOut:
    """Rewrite one paragraph of the pending draft with the writer model, keeping citations to known
    evidence only. The result is returned for the editor; the user still approves or edits."""
    r = await session.get(Run, thread_id)
    if r is None or r.user_id != user.user_id or r.kind != "bid":
        raise HTTPException(404, "run not found")
    values, nxt = await runtime().state_values(thread_id, "bid", user.user_id)
    draft = values.get("proposal_draft")
    if not draft or not nxt:
        raise HTTPException(409, "no pending draft on this run")
    paras = [p for p in re.split(r"\n\s*\n", draft["cover_letter"]) if p.strip()]
    if body.paragraph_index >= len(paras):
        raise HTTPException(400, f"draft has {len(paras)} paragraphs")
    system, _ = load_prompt("writer")
    prompt = (
        f"Rewrite ONLY paragraph {body.paragraph_index + 1} of this cover letter. Keep every other paragraph unchanged and do not output them. "
        f"Keep citations to the evidence ids provided; add no new claims. {('Instruction from the user: ' + body.instruction) if body.instruction else ''}\n\n"
        f"Evidence:\n{evidence_block(values.get('evidence', []))[:5000]}\n\nParagraph to rewrite:\n{paras[body.paragraph_index]}\n\nOutput the new paragraph only."
    )
    resp = await llm.ainvoke_for_node(
        "writer",
        [SystemMessage(content=f"{system}\n\n{SYSTEM_GUARD}"), HumanMessage(content=prompt)],
    )
    new_para = str(resp.content).strip()
    known = {e["evidence_id"] for e in values.get("evidence", [])}
    for cid in re.findall(r"\[([0-9a-f]{8,32})\]", new_para):
        if cid not in known:
            new_para = new_para.replace(f"[{cid}]", "")
    paras[body.paragraph_index] = new_para
    return RegenerateOut(
        paragraph_index=body.paragraph_index, paragraph=new_para, cover_letter="\n\n".join(paras)
    )
