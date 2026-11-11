"""Load the seed files into the GigSim database."""

from __future__ import annotations

import gzip
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gigsim import clients as sim_clients
from gigsim.models import Account, Client, Job

SEED_DIR = Path(__file__).resolve().parent / "seed"


def _client_key(job: dict[str, Any]) -> str:
    c = job["client"]
    if job["source"].startswith("synthetic:adversarial"):
        return "adv:" + job["job_id"]
    if c.get("payment_verified") is None:  # 50k rows carry no client fields -> one client per job
        return "anon:" + job["job_id"]
    raw = f"{c.get('country')}|{c.get('total_spent')}|{c.get('rating')}|{c.get('reviews_count')}"
    return "k:" + raw


def _budget_hint(job: dict[str, Any]) -> float | None:
    if job["payment_type"] == "fixed":
        return job.get("budget")
    return job.get("hourly_max") or job.get("hourly_min")


def load_seed_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    with gzip.open(SEED_DIR / "jobs.jsonl.gz", "rt", encoding="utf-8") as f:
        jobs += [json.loads(line) for line in f]
    adv = SEED_DIR / "jobs_adversarial.jsonl"
    if adv.exists():
        jobs += [json.loads(line) for line in adv.open(encoding="utf-8")]
    return jobs


def seed_database(
    session: Session,
    *,
    initial_open_per_persona: int = 100,
    seed: int = 42,
    market_stats: dict | None = None,
) -> dict[str, int]:
    if session.scalar(select(Job).limit(1)) is not None:
        return {"jobs": 0, "clients": 0, "skipped": 1}
    rng = random.Random(seed)
    stats = market_stats or json.loads((SEED_DIR / "market_stats.json").read_text(encoding="utf-8"))
    jobs = load_seed_jobs()
    rng.shuffle(jobs)

    clients: dict[str, Client] = {}
    for job in jobs:
        key = _client_key(job)
        cid = "cl_" + hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:12]
        c = job["client"]
        if cid not in clients:
            adversarial = key.startswith("adv:")
            r = random.Random(cid)
            spent = (
                c.get("total_spent")
                if c.get("total_spent") is not None
                else r.choice([0.0, 0.0, 250.0, 1200.0, 8000.0, 25000.0])
            )
            verified = (
                c.get("payment_verified")
                if c.get("payment_verified") is not None
                else (r.random() < 0.65)
            )
            reviews = (
                c.get("reviews_count")
                if c.get("reviews_count") is not None
                else r.choice([0, 0, 2, 7, 15])
            )
            rating = (
                c.get("rating")
                if c.get("rating") is not None
                else (round(r.uniform(3.8, 5.0), 2) if reviews else None)
            )
            clients[cid] = Client(
                client_id=cid,
                display_name=f"Client {cid[-4:].upper()}",
                country=c.get("country"),
                payment_verified=bool(verified),
                total_spent=float(spent or 0.0),
                rating=rating,
                reviews_count=int(reviews or 0),
                hires=int((reviews or 0) * r.uniform(1.0, 1.6)),
                jobs_posted=0,
                avg_hourly_paid=round(r.uniform(12, 60), 2) if spent else None,
                member_since=str(r.randint(2015, 2025)),
                industry=sim_clients.industry_for(cid),
                adversarial=adversarial,
                hidden_prefs=sim_clients.make_hidden_prefs(
                    cid, job.get("skills", []), _budget_hint(job), adversarial
                ),
            )
            session.add(clients[cid])
        clients[cid].jobs_posted += 1

        persona = job["persona"]
        default_connects = int(stats["personas"].get(persona, {}).get("connects_cost_mode") or 8)
        session.add(
            Job(
                job_id=job["job_id"],
                client_id=cid,
                title=job["title"],
                description=job["description"],
                skills=job.get("skills", []),
                category=job.get("category"),
                persona_hint=persona,
                payment_type=job["payment_type"],
                budget=job.get("budget"),
                hourly_min=job.get("hourly_min"),
                hourly_max=job.get("hourly_max"),
                experience_level=job.get("experience_level"),
                duration=job.get("duration"),
                screening_questions=sim_clients.make_screening_questions(
                    job["job_id"], job.get("skills", [])
                ),
                connects_cost=int(job.get("connects_cost") or default_connects),
                applicants=rng.randint(0, 40),
                status="pool",
                source=job["source"],
                release_order=0,
            )
        )
    session.flush()

    # Assign release order per persona and open the first batch.
    opened = 0
    for persona in ("ai_ml", "fullstack", "data_analyst"):
        rows = list(session.scalars(select(Job).where(Job.persona_hint == persona)))
        rng.shuffle(rows)
        for i, row in enumerate(rows):
            row.release_order = i
            if i < initial_open_per_persona:
                row.status = "open"
                row.posted_at = sim_clients.utc_offset_now(-rng.randint(1, 72 * 60))
                opened += 1
    session.commit()
    return {"jobs": len(jobs), "clients": len(clients), "opened": opened}


def ensure_accounts(session: Session, accounts: list[dict[str, str]]) -> None:
    for a in accounts:
        existing = session.scalar(
            select(Account).where(Account.freelancer_id == a["freelancer_id"])
        )
        if existing is None:
            session.add(
                Account(
                    api_key=a["api_key"],
                    freelancer_id=a["freelancer_id"],
                    display_name=a.get("display_name", a["freelancer_id"]),
                    connects=int(a.get("connects", 200)),
                )
            )
        elif existing.api_key != a["api_key"]:  # token rotated in config: re-key the account
            session.delete(existing)
            session.flush()
            session.add(
                Account(
                    api_key=a["api_key"],
                    freelancer_id=a["freelancer_id"],
                    display_name=existing.display_name,
                    connects=existing.connects,
                )
            )
    session.commit()
