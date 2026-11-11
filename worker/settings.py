"""Arq worker (E1): scheduled scouting per saved search and long graph runs, outside web requests.

    uv run arq worker.settings.WorkerSettings

Jobs are idempotent: a bid run is keyed by (user, job_id, portfolio version) so a worker restart
never double-analyses, and submissions are idempotent in the marketplace layer. Failures after
the retry budget land in the dead-letter table (Run.status = needs_attention).
"""

from __future__ import annotations

import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from agent import settings
from worker import tasks

log = logging.getLogger("gigbid.worker")


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.env().redis_url)


async def startup(ctx: dict[str, Any]) -> None:
    await tasks.init(ctx)


async def shutdown(ctx: dict[str, Any]) -> None:
    await tasks.close(ctx)


class WorkerSettings:
    functions = [
        tasks.run_bid,
        tasks.run_conversation,
        tasks.scout_search,
        tasks.sync_pipeline,
        tasks.ingest_portfolio,
    ]
    cron_jobs = [
        cron(tasks.scout_due_searches, minute={0, 15, 30, 45}, run_at_startup=True, unique=True),
        cron(tasks.sync_all_pipelines, minute={5, 35}, unique=True),
        cron(tasks.poll_conversations, minute={10, 40}, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    max_jobs = 2  # graph runs are memory-heavy on small hosts
    job_timeout = 900
    max_tries = 3
    retry_jobs = True
    keep_result = 3600
