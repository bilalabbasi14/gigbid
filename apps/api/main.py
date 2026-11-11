"""GigBid API. One trace id flows from the request through the graph, MCP servers and audit log."""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agent import settings
from agent.marketplace_port import make_marketplace
from agent.mcp_client import DEGRADED
from apps.api import db, streaming
from apps.api import runtime as rt
from apps.api.routers import (
    analytics,
    approvals,
    auth,
    jobs,
    messages,
    pipeline,
    portfolio,
    runs,
    settings_router,
)
from apps.api.schemas import HealthOut

log = logging.getLogger("gigbid.api")
DEPS_OVERRIDE: Any = None  # tests inject fake deps here


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    env = settings.env()
    logging.basicConfig(level=env.log_level)
    db.init_engine()
    await db.create_all()
    deps = DEPS_OVERRIDE
    if (
        deps is None
        and os.environ.get("GIGBID_IN_PROCESS_MCP", "0" if env.app_env == "production" else "1")
        == "1"
    ):
        from agent.deps import Deps
        from agent.mcp_client import ToolProvider, in_process_loader

        deps = Deps(tools=ToolProvider(loader=in_process_loader))
    rt.RUNTIME = await rt.Runtime.create(deps, persistent=env.app_env != "test")
    if env.app_env != "test" and os.environ.get("GIGBID_WARM_MODELS", "1") == "1":
        try:
            from rag import embeddings

            embeddings.warm()
        except Exception as exc:  # noqa: BLE001
            log.warning("model warm-up skipped: %s", exc)
    yield
    await rt.RUNTIME.close()


app = FastAPI(
    title="GigBid API",
    version="0.5.0",
    lifespan=lifespan,
    description="Multi-agent freelancer copilot. Every proposal and message needs human approval.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.env().web_base_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex[:16]
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["x-trace-id"] = trace_id
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(
        {"detail": "internal error", "trace_id": getattr(request.state, "trace_id", None)},
        status_code=500,
    )


for r in (
    auth.router,
    settings_router.router,
    jobs.router,
    approvals.router,
    messages.router,
    pipeline.router,
    portfolio.router,
    runs.router,
    streaming.router,
    analytics.router,
):
    app.include_router(r)


@app.get("/health", response_model=HealthOut, tags=["health"])
async def health() -> HealthOut:
    env = settings.env()
    reachable = False
    try:
        reachable = await make_marketplace().health()
    except Exception:  # noqa: BLE001
        reachable = False
    status = "ok" if reachable and not DEGRADED.failing else "degraded"
    return HealthOut(
        status=status,
        marketplace_mode=env.marketplace_mode,
        marketplace_reachable=reachable,
        degraded=DEGRADED.snapshot(),
        policy_version=int(settings.config().policy_version),
        model_profile=env.model_profile,
    )


@app.get("/", include_in_schema=False)
async def root() -> dict[str, Any]:
    return {"service": "gigbid-api", "docs": "/docs"}
