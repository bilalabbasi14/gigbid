"""GigSim: a marketplace simulator with a REST API (student-built stand-in, see README.md).

Run: uvicorn gigsim.app:app --port 8081
Auth: `Authorization: Bearer <api_key>` on every non-admin route. Accounts come from
GIGSIM_ACCOUNTS ("key:freelancer_id:name,key2:..."), default dev-token:freelancer_dev:Dev.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import queue
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from gigsim import client_llm
from gigsim import clients as sim_clients
from gigsim.models import (
    Account,
    Client,
    Event,
    IdempotencyRecord,
    Job,
    Message,
    Proposal,
    make_engine,
    session_factory,
    utcnow,
)
from gigsim.ratelimit import Chaos, TokenBucket
from gigsim.seed import SEED_DIR, ensure_accounts, seed_database

POLICY_PATH = SEED_DIR / "policy.json"

app = FastAPI(title="GigSim marketplace simulator", version="0.2.0")
engine = make_engine()
SessionLocal = session_factory(engine)
bucket = TokenBucket(int(os.environ.get("GIGSIM_RATE_PER_MINUTE", "60")))
chaos = Chaos()


def parse_accounts() -> list[dict[str, str]]:
    # Default account: the token the app uses (GIGSIM_API_TOKEN, also read from .env when present).
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    except ImportError:
        pass
    default_token = os.environ.get("GIGSIM_API_TOKEN", "dev-token")
    raw = os.environ.get("GIGSIM_ACCOUNTS", f"{default_token}:freelancer_dev:Dev Freelancer")
    out = []
    for item in raw.split(","):
        key, fid, *rest = item.split(":")
        out.append(
            {
                "api_key": key.strip(),
                "freelancer_id": fid.strip(),
                "display_name": (rest[0] if rest else fid).strip(),
            }
        )
    return out


@app.on_event("startup")
def _startup() -> None:
    with SessionLocal() as s:
        ensure_accounts(s, parse_accounts())
        if os.environ.get("GIGSIM_AUTOSEED", "1") == "1":
            seed_database(s)
        if sim_clients.mode() == "llm":
            for p in s.scalars(select(Proposal).where(Proposal.status == "submitted")).all():
                if (p.client_decision or {}).get("pending"):
                    _DECIDER.submit(p.proposal_id)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def auth(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> Account:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    acct = db.get(Account, authorization.split(" ", 1)[1].strip())
    if acct is None:
        raise HTTPException(401, "invalid token")
    return acct


@app.middleware("http")
async def limits_and_chaos(request: Request, call_next):  # type: ignore[no-untyped-def]
    path = request.url.path
    if path.startswith(("/health", "/admin", "/docs", "/openapi")):
        return await call_next(request)
    key = request.headers.get("authorization", "anon")
    ok, retry = bucket.take(key)
    if not ok:
        return JSONResponse(
            {"error": "rate_limited", "retry_after": retry},
            status_code=429,
            headers={"Retry-After": str(int(retry) + 1)},
        )
    if chaos.should_fail():
        return JSONResponse(
            {"error": "simulated_upstream_failure"}, status_code=503, headers={"Retry-After": "2"}
        )
    return await call_next(request)


# ---------- serialisers ----------
def job_out(j: Job, c: Client | None = None) -> dict[str, Any]:
    return {
        "job_id": j.job_id,
        "title": j.title,
        "description": j.description,
        "skills": j.skills,
        "category": j.category,
        "payment_type": j.payment_type,
        "budget": j.budget,
        "hourly_min": j.hourly_min,
        "hourly_max": j.hourly_max,
        "experience_level": j.experience_level,
        "duration": j.duration,
        "screening_questions": j.screening_questions,
        "connects_cost": j.connects_cost,
        "applicants": j.applicants,
        "status": j.status,
        "posted_at": j.posted_at.isoformat() + "Z" if j.posted_at else None,
        "client_id": j.client_id,
        "client": client_summary(c) if c else None,
    }


def client_summary(c: Client) -> dict[str, Any]:
    return {
        "client_id": c.client_id,
        "country": c.country,
        "payment_verified": c.payment_verified,
        "total_spent": c.total_spent,
        "rating": c.rating,
        "reviews_count": c.reviews_count,
        "hires": c.hires,
        "jobs_posted": c.jobs_posted,
        "member_since": c.member_since,
    }


def proposal_out(p: Proposal) -> dict[str, Any]:
    return {
        "proposal_id": p.proposal_id,
        "job_id": p.job_id,
        "status": p.status,
        "bid_amount": p.bid_amount,
        "bid_type": p.bid_type,
        "connects_spent": p.connects_spent,
        "thread_id": p.thread_id,
        "created_at": p.created_at.isoformat() + "Z",
        "updated_at": p.updated_at.isoformat() + "Z",
        "cover_letter": p.cover_letter,
        "screening_answers": p.screening_answers,
        "decided": not (p.client_decision or {}).get("pending"),
    }


def message_out(m: Message) -> dict[str, Any]:
    return {
        "message_id": m.message_id,
        "thread_id": m.thread_id,
        "proposal_id": m.proposal_id,
        "sender": m.sender,
        "body": m.body,
        "created_at": m.created_at.isoformat() + "Z",
        "read": m.read,
    }


def emit(db: Session, freelancer_id: str, kind: str, payload: dict[str, Any]) -> None:
    db.add(Event(freelancer_id=freelancer_id, kind=kind, payload=payload))


# ---------- public read routes ----------
@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "gigsim", "origin": "student-built", "version": app.version}


@app.get("/policy")
def policy() -> dict[str, Any]:
    if POLICY_PATH.exists():
        return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    return {
        "version": 1,
        "connects": {"cost_per_proposal_default": 8, "boost_allowed": False},
        "rules": [],
    }


@app.get("/jobs")
def search_jobs(
    q: str | None = None,
    skills: str | None = Query(default=None, description="comma-separated"),
    payment_type: str | None = None,
    min_budget: float | None = None,
    posted_after: str | None = None,
    page: int = 1,
    limit: int = Query(default=20, le=50),
    acct: Account = Depends(auth),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(Job).where(Job.status == "open")
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(func.lower(Job.title).like(like), func.lower(Job.description).like(like))
        )
    if skills:
        for sk in [s.strip().lower() for s in skills.split(",") if s.strip()]:
            stmt = stmt.where(func.lower(func.json_extract(Job.skills, "$")).like(f"%{sk}%"))
    if payment_type:
        stmt = stmt.where(Job.payment_type == payment_type)
    if min_budget is not None:
        stmt = stmt.where(or_(Job.budget >= min_budget, Job.hourly_max >= min_budget))
    if posted_after:
        stmt = stmt.where(Job.posted_at >= dt.datetime.fromisoformat(posted_after.replace("Z", "")))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Job.posted_at.desc()).offset((page - 1) * limit).limit(limit)
    ).all()
    return {"total": total, "page": page, "limit": limit, "items": [job_out(j) for j in rows]}


@app.get("/jobs/{job_id}")
def get_job(
    job_id: str, acct: Account = Depends(auth), db: Session = Depends(get_db)
) -> dict[str, Any]:
    j = db.get(Job, job_id)
    if j is None or j.status == "pool":
        raise HTTPException(404, "job not found")
    return job_out(j, db.get(Client, j.client_id))


@app.get("/clients/{client_id}")
def get_client(
    client_id: str, acct: Account = Depends(auth), db: Session = Depends(get_db)
) -> dict[str, Any]:
    c = db.get(Client, client_id)
    if c is None:
        raise HTTPException(404, "client not found")
    past = db.scalars(
        select(Job)
        .where(Job.client_id == client_id, Job.status != "pool")
        .order_by(Job.posted_at.desc())
        .limit(10)
    ).all()
    out = client_summary(c)
    out.update(
        {
            "industry": c.industry,
            "avg_hourly_paid": c.avg_hourly_paid,
            "past_jobs": [
                {
                    "job_id": j.job_id,
                    "title": j.title,
                    "payment_type": j.payment_type,
                    "budget": j.budget,
                    "status": j.status,
                }
                for j in past
            ],
        }
    )
    return out


@app.get("/me")
def me(acct: Account = Depends(auth)) -> dict[str, Any]:
    return {
        "freelancer_id": acct.freelancer_id,
        "display_name": acct.display_name,
        "connects": acct.connects,
    }


@app.get("/me/connects")
def connects(acct: Account = Depends(auth)) -> dict[str, Any]:
    return {"freelancer_id": acct.freelancer_id, "balance": acct.connects}


# ---------- proposals ----------
class ProposalIn(BaseModel):
    job_id: str
    cover_letter: str = Field(min_length=50, max_length=5000)
    bid_amount: float = Field(gt=0)
    bid_type: str = Field(pattern="^(fixed|hourly)$")
    screening_answers: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=8, max_length=128)
    dry_run: bool = False


def _scoped(fid: str, endpoint: str, key: str) -> str:
    """Idempotency keys belong to one account and one endpoint, as on a real marketplace: two
    freelancers may use the same key without colliding."""
    return f"{fid}:{endpoint}:{key}"


def _idempotent(db: Session, key: str, fid: str, endpoint: str) -> dict[str, Any] | None:
    rec = db.get(IdempotencyRecord, _scoped(fid, endpoint, key))
    if rec and rec.freelancer_id == fid and rec.endpoint == endpoint:
        return {**rec.response, "idempotent_replay": True}
    return None


@app.post("/proposals", status_code=201)
def create_proposal(
    body: ProposalIn, acct: Account = Depends(auth), db: Session = Depends(get_db)
) -> dict[str, Any]:
    if (
        replay := _idempotent(db, body.idempotency_key, acct.freelancer_id, "proposals")
    ) is not None:
        return replay
    j = db.get(Job, body.job_id)
    if j is None or j.status != "open":
        raise HTTPException(404, "job not open")
    if body.bid_type != j.payment_type:
        raise HTTPException(422, f"bid_type must be {j.payment_type} for this job")
    existing = db.scalar(
        select(Proposal).where(
            Proposal.job_id == j.job_id, Proposal.freelancer_id == acct.freelancer_id
        )
    )
    if existing:
        raise HTTPException(409, "already applied to this job")
    preview = {
        "job_id": j.job_id,
        "connects_cost": j.connects_cost,
        "balance_after": acct.connects - j.connects_cost,
        "bid_amount": body.bid_amount,
        "bid_type": body.bid_type,
        "cover_letter": body.cover_letter,
        "screening_answers": body.screening_answers,
    }
    if body.dry_run:
        return {"dry_run": True, "would_send": preview}
    if acct.connects < j.connects_cost:
        raise HTTPException(402, "insufficient connects")
    acct.connects -= j.connects_cost
    db.add(acct)
    pid = "prop_" + uuid.uuid4().hex[:12]
    thread_id = "thr_" + uuid.uuid4().hex[:12]
    client = db.get(Client, j.client_id)
    # seed the client's dice on the job and the letter, not the random proposal id, so the same
    # proposal to the same job always gets the same reaction (reproducible outcome evaluations)
    prefs = client.hidden_prefs if client else {}
    deferred = sim_clients.mode() == "llm" and not prefs.get("never_replies")
    decision = (
        None
        if deferred
        else sim_clients.decide(
            job_out(j),
            prefs,
            _seed_key(j.job_id, body.cover_letter),
            body.cover_letter,
            body.bid_amount,
            body.screening_answers,
        )
    )
    p = Proposal(
        proposal_id=pid,
        freelancer_id=acct.freelancer_id,
        job_id=j.job_id,
        cover_letter=body.cover_letter,
        bid_amount=body.bid_amount,
        bid_type=body.bid_type,
        screening_answers=body.screening_answers,
        connects_spent=j.connects_cost,
        status="submitted",
        client_decision={"pending": True} if decision is None else decision["breakdown"],
        thread_id=thread_id,
    )
    db.add(p)
    j.applicants += 1
    emit(db, acct.freelancer_id, "proposal.submitted", {"proposal_id": pid, "job_id": j.job_id})
    if decision is not None:
        _apply_decision(db, p, decision)
    db.flush()
    resp = {"proposal": proposal_out(p), "connects_remaining": acct.connects}
    db.add(
        IdempotencyRecord(
            key=_scoped(acct.freelancer_id, "proposals", body.idempotency_key),
            freelancer_id=acct.freelancer_id,
            endpoint="proposals",
            response=resp,
        )
    )
    db.commit()
    if decision is None:
        _DECIDER.submit(pid)
    return resp


def _seed_key(job_id: str, cover_letter: str) -> str:
    # seed the client's dice on the job and the letter, not the random proposal id, so the same
    # proposal to the same job always gets the same reaction (reproducible outcome evaluations)
    return f"{job_id}:{hashlib.sha256(cover_letter.encode()).hexdigest()[:16]}"


def _apply_decision(db: Session, p: Proposal, decision: dict[str, Any]) -> None:
    """Apply a client's reaction: status, event and (for a reply) the client's first message."""
    p.client_decision = decision["breakdown"]
    outcome = decision["outcome"]
    if outcome == "submitted":
        return
    p.status = outcome
    p.updated_at = utcnow()
    emit(
        db,
        p.freelancer_id,
        f"proposal.{outcome}",
        {"proposal_id": p.proposal_id, "job_id": p.job_id},
    )
    if decision["message"]:
        db.add(
            Message(
                message_id="msg_" + uuid.uuid4().hex[:12],
                thread_id=p.thread_id,
                proposal_id=p.proposal_id,
                freelancer_id=p.freelancer_id,
                sender="client",
                body=decision["message"],
            )
        )
        emit(
            db,
            p.freelancer_id,
            "message.received",
            {"thread_id": p.thread_id, "proposal_id": p.proposal_id},
        )


def decide_pending(proposal_id: str) -> None:
    """The client reads a proposal and reacts (LLM mode). Safe to call twice."""
    with SessionLocal() as db:
        p = db.get(Proposal, proposal_id)
        if p is None or not (p.client_decision or {}).get("pending"):
            return
        j = db.get(Job, p.job_id)
        client = db.get(Client, j.client_id) if j else None
        prefs = client.hidden_prefs if client else {}
        job = job_out(j) if j else {"job_id": p.job_id, "title": "", "description": ""}
        view = client_llm.judge(job, prefs, p.cover_letter, p.bid_amount, p.screening_answers or [])
        decision = sim_clients.decide(
            job,
            prefs,
            _seed_key(p.job_id, p.cover_letter),
            p.cover_letter,
            p.bid_amount,
            p.screening_answers or [],
            llm_view=view,
        )
        if view is None:
            decision["breakdown"]["llm_unavailable"] = True
        _apply_decision(db, p, decision)
        db.commit()


class _Decider:
    """One background thread works through pending client decisions in order, so a slow local
    model never blocks a request and never runs twice at once on a small machine."""

    def __init__(self) -> None:
        self.q: queue.Queue[str] = queue.Queue()
        self.thread: threading.Thread | None = None

    def submit(self, proposal_id: str) -> None:
        if os.environ.get("GIGSIM_DECIDE_INLINE") == "1":  # tests
            decide_pending(proposal_id)
            return
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._run, name="gigsim-decider", daemon=True)
            self.thread.start()
        self.q.put(proposal_id)

    def _run(self) -> None:
        while True:
            pid = self.q.get()
            try:
                decide_pending(pid)
            except Exception:  # noqa: BLE001 - keep the worker alive; the proposal stays pending
                logging.getLogger("gigsim").exception("client decision failed for %s", pid)


_DECIDER = _Decider()


@app.get("/proposals")
def list_proposals(
    status: str | None = None, acct: Account = Depends(auth), db: Session = Depends(get_db)
) -> dict[str, Any]:
    stmt = select(Proposal).where(Proposal.freelancer_id == acct.freelancer_id)
    if status:
        stmt = stmt.where(Proposal.status == status)
    return {
        "items": [
            proposal_out(p) for p in db.scalars(stmt.order_by(Proposal.created_at.desc())).all()
        ]
    }


@app.get("/proposals/{proposal_id}")
def get_proposal(
    proposal_id: str, acct: Account = Depends(auth), db: Session = Depends(get_db)
) -> dict[str, Any]:
    p = db.get(Proposal, proposal_id)
    if p is None or p.freelancer_id != acct.freelancer_id:
        raise HTTPException(404, "proposal not found")
    return proposal_out(p)


# ---------- messages ----------
class MessageIn(BaseModel):
    thread_id: str
    body: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    dry_run: bool = False


@app.get("/threads")
def list_threads(acct: Account = Depends(auth), db: Session = Depends(get_db)) -> dict[str, Any]:
    props = db.scalars(
        select(Proposal).where(
            Proposal.freelancer_id == acct.freelancer_id, Proposal.thread_id.is_not(None)
        )
    ).all()
    out = []
    for p in props:
        msgs = db.scalars(
            select(Message).where(Message.thread_id == p.thread_id).order_by(Message.created_at)
        ).all()
        if not msgs:
            continue
        j = db.get(Job, p.job_id)
        out.append(
            {
                "thread_id": p.thread_id,
                "proposal_id": p.proposal_id,
                "job_id": p.job_id,
                "job_title": j.title if j else None,
                "client_id": j.client_id if j else None,
                "status": p.status,
                "unread": sum(1 for m in msgs if m.sender == "client" and not m.read),
                "last_message": message_out(msgs[-1]),
            }
        )
    return {"items": out}


@app.get("/messages")
def list_messages(
    thread_id: str, acct: Account = Depends(auth), db: Session = Depends(get_db)
) -> dict[str, Any]:
    msgs = db.scalars(
        select(Message)
        .where(Message.thread_id == thread_id, Message.freelancer_id == acct.freelancer_id)
        .order_by(Message.created_at)
    ).all()
    for m in msgs:
        if m.sender == "client":
            m.read = True
    db.commit()
    return {"items": [message_out(m) for m in msgs]}


@app.post("/messages", status_code=201)
def send_message(
    body: MessageIn, acct: Account = Depends(auth), db: Session = Depends(get_db)
) -> dict[str, Any]:
    if (
        replay := _idempotent(db, body.idempotency_key, acct.freelancer_id, "messages")
    ) is not None:
        return replay
    p = db.scalar(
        select(Proposal).where(
            Proposal.thread_id == body.thread_id, Proposal.freelancer_id == acct.freelancer_id
        )
    )
    if p is None:
        raise HTTPException(404, "thread not found")
    if body.dry_run:
        return {"dry_run": True, "would_send": {"thread_id": body.thread_id, "body": body.body}}
    mid = "msg_" + uuid.uuid4().hex[:12]
    db.add(
        Message(
            message_id=mid,
            thread_id=body.thread_id,
            proposal_id=p.proposal_id,
            freelancer_id=acct.freelancer_id,
            sender="freelancer",
            body=body.body,
            read=True,
        )
    )
    emit(db, acct.freelancer_id, "message.sent", {"thread_id": body.thread_id})
    j = db.get(Job, p.job_id)
    client = db.get(Client, j.client_id) if j else None
    reply = sim_clients.client_followup(client.hidden_prefs if client else {}, body.body, mid)
    if reply:
        db.add(
            Message(
                message_id="msg_" + uuid.uuid4().hex[:12],
                thread_id=body.thread_id,
                proposal_id=p.proposal_id,
                freelancer_id=acct.freelancer_id,
                sender="client",
                body=reply,
            )
        )
        emit(
            db,
            acct.freelancer_id,
            "message.received",
            {"thread_id": body.thread_id, "proposal_id": p.proposal_id},
        )
    resp = {"message_id": mid, "thread_id": body.thread_id, "client_replied": bool(reply)}
    db.add(
        IdempotencyRecord(
            key=_scoped(acct.freelancer_id, "messages", body.idempotency_key),
            freelancer_id=acct.freelancer_id,
            endpoint="messages",
            response=resp,
        )
    )
    db.commit()
    return resp


@app.get("/events")
def list_events(
    since_id: int = 0, acct: Account = Depends(auth), db: Session = Depends(get_db)
) -> dict[str, Any]:
    rows = db.scalars(
        select(Event)
        .where(Event.freelancer_id == acct.freelancer_id, Event.event_id > since_id)
        .order_by(Event.event_id)
        .limit(200)
    ).all()
    return {
        "items": [
            {
                "event_id": e.event_id,
                "kind": e.kind,
                "payload": e.payload,
                "created_at": e.created_at.isoformat() + "Z",
            }
            for e in rows
        ]
    }


# ---------- admin (no auth; not exposed publicly in deployment) ----------
@app.post("/admin/tick")
def admin_tick(
    n: int = 10, persona: str | None = None, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Release the next n pooled jobs as 'open' (simulates new postings)."""
    stmt = select(Job).where(Job.status == "pool")
    if persona:
        stmt = stmt.where(Job.persona_hint == persona)
    rows = db.scalars(stmt.order_by(Job.release_order).limit(n)).all()
    for r in rows:
        r.status = "open"
        r.posted_at = utcnow()
    db.commit()
    return {"released": [r.job_id for r in rows]}


@app.post("/admin/reset")
def admin_reset(db: Session = Depends(get_db)) -> dict[str, Any]:
    for model in (Message, Proposal, IdempotencyRecord, Event, Job, Client, Account):
        db.query(model).delete()
    db.commit()
    ensure_accounts(db, parse_accounts())
    return {"reset": True, **seed_database(db)}


@app.post("/admin/open")
def admin_open(job_ids: list[str], db: Session = Depends(get_db)) -> dict[str, Any]:
    """Open specific pooled jobs (evaluation runs use a fixed job set)."""
    opened = []
    for jid in job_ids:
        j = db.get(Job, jid)
        if j is not None and j.status != "open":
            j.status = "open"
            j.posted_at = utcnow()
            opened.append(jid)
    db.commit()
    return {"opened": opened}


@app.post("/admin/accounts")
def admin_account(
    api_key: str, freelancer_id: str, connects: int = 1000, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Create (or reset) a freelancer account, e.g. one per evaluation run."""
    acct = db.get(Account, api_key)
    if acct is None:
        old = db.scalar(select(Account).where(Account.freelancer_id == freelancer_id))
        if old is not None:
            db.delete(old)
            db.flush()
        db.add(
            Account(
                api_key=api_key,
                freelancer_id=freelancer_id,
                display_name=freelancer_id,
                connects=connects,
            )
        )
    else:
        acct.connects = connects
    db.commit()
    return {"api_key": api_key, "freelancer_id": freelancer_id, "connects": connects}


@app.post("/admin/connects")
def admin_connects(
    freelancer_id: str, balance: int, db: Session = Depends(get_db)
) -> dict[str, Any]:
    acct = db.scalar(select(Account).where(Account.freelancer_id == freelancer_id))
    if acct is None:
        raise HTTPException(404, "account not found")
    acct.connects = balance
    db.commit()
    return {"freelancer_id": freelancer_id, "balance": balance}


@app.get("/admin/stats")
def admin_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    by_status = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    props = dict(db.execute(select(Proposal.status, func.count()).group_by(Proposal.status)).all())
    return {
        "jobs": by_status,
        "proposals": props,
        "clients": db.scalar(select(func.count(Client.client_id))),
    }
