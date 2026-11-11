"""`make seed`: create the reviewer login preloaded with a persona, a default saved search, and
make sure the persona corpora are indexed. Idempotent.

  uv run python -m scripts.seed [--email reviewer@gigbid.local] [--persona ai_ml] [--no-ingest]
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from agent import settings
from apps.api import db
from apps.api.auth.security import hash_password
from apps.api.db import SavedSearch, User

SEARCHES = {
    "ai_ml": [
        ("Machine learning", "machine learning", ["Python"]),
        ("RAG and chatbots", "chatbot", []),
        ("Computer vision", "computer vision", []),
    ],
    "fullstack": [
        ("React and Next.js", "react", []),
        ("Django APIs", "django", []),
        ("Full stack apps", "full stack", []),
    ],
    "data_analyst": [
        ("Power BI", "power bi", []),
        ("SQL analytics", "sql", []),
        ("Dashboards", "dashboard", []),
    ],
}


async def main() -> None:
    ap = argparse.ArgumentParser()
    env = settings.env()
    ap.add_argument("--email", default=env.reviewer_email)
    ap.add_argument("--password", default=env.reviewer_password)
    ap.add_argument("--persona", default="ai_ml", choices=list(SEARCHES))
    ap.add_argument("--no-ingest", action="store_true")
    args = ap.parse_args()

    db.init_engine()
    await db.create_all()
    async with db.session_factory()() as s:
        user = await s.scalar(select(User).where(User.email == args.email.lower()))
        if user is None:
            user = User(
                email=args.email.lower(),
                password_hash=hash_password(args.password),
                display_name="Reviewer",
                role="reviewer",
                persona=args.persona,
                settings_json={
                    "persona": args.persona,
                    "autonomy": "auto_skip",
                    "weekly_connects_budget": 80,
                    "hourly_rate": 55,
                    "hourly_floor": 30,
                    "min_project_budget": 100,
                    "onboarded": True,
                    "marketplace_mode": "gigsim",
                },
            )
            s.add(user)
            await s.flush()
            print(f"created reviewer {args.email} with persona {args.persona}")
        else:
            user.password_hash = hash_password(args.password)
            user.persona = args.persona
            print(f"reviewer {args.email} already exists; password reset")
        existing = {
            r.name
            for r in (
                await s.scalars(select(SavedSearch).where(SavedSearch.user_id == user.user_id))
            ).all()
        }
        for name, query, skills in SEARCHES[args.persona]:
            if name not in existing:
                s.add(
                    SavedSearch(
                        user_id=user.user_id,
                        name=name,
                        query=query,
                        skills=skills,
                        interval_minutes=180,
                    )
                )
        await s.commit()
    if not args.no_ingest:
        from rag.index.pg import ChunkStore
        from rag.ingest.cli import PERSONAS_ROOT, ingest_persona

        store = ChunkStore()
        for p in SEARCHES:
            if (PERSONAS_ROOT / p / "projects.json").exists():
                print(p, ingest_persona(store, PERSONAS_ROOT / p))


if __name__ == "__main__":
    asyncio.run(main())
