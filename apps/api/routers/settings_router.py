from __future__ import annotations

import base64
import hashlib
import secrets
import urllib.parse
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent import settings
from agent.memory import store as memstore
from apps.api.auth.security import CurrentUser
from apps.api.auth.token_store import delete_oauth_token, save_oauth_token
from apps.api.db import OAuthToken, SavedSearch, get_session
from apps.api.routers.auth import user_out
from apps.api.runtime import runtime
from apps.api.schemas import (
    ConnectedAccount,
    MemoryView,
    SavedSearchIn,
    SavedSearchOut,
    UserOut,
    UserSettingsIn,
)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=UserOut)
async def get_settings(user: CurrentUser) -> UserOut:
    return user_out(user)


@router.put("", response_model=UserOut)
async def put_settings(
    body: UserSettingsIn, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> UserOut:
    st = dict(user.settings_json or {})
    for k, v in body.model_dump(exclude_none=True).items():
        st[k] = v
    if body.persona:
        user.persona = body.persona
        st["persona"] = body.persona
    user.settings_json = st
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user_out(user)


# ---- saved searches ----
def _ss_out(s: SavedSearch) -> SavedSearchOut:
    return SavedSearchOut(
        search_id=s.search_id,
        name=s.name,
        query=s.query,
        skills=s.skills or [],
        payment_type=s.payment_type,
        min_budget=s.min_budget,
        interval_minutes=s.interval_minutes,
        enabled=s.enabled,
        last_run_at=s.last_run_at,
    )


@router.get("/searches", response_model=list[SavedSearchOut])
async def list_searches(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[SavedSearchOut]:
    rows = (
        await session.scalars(
            select(SavedSearch)
            .where(SavedSearch.user_id == user.user_id)
            .order_by(SavedSearch.name)
        )
    ).all()
    return [_ss_out(r) for r in rows]


@router.post("/searches", response_model=SavedSearchOut, status_code=201)
async def create_search(
    body: SavedSearchIn, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> SavedSearchOut:
    row = SavedSearch(user_id=user.user_id, **body.model_dump())
    session.add(row)
    await session.commit()
    return _ss_out(row)


@router.put("/searches/{search_id}", response_model=SavedSearchOut)
async def update_search(
    search_id: str,
    body: SavedSearchIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SavedSearchOut:
    row = await session.get(SavedSearch, search_id)
    if row is None or row.user_id != user.user_id:
        raise HTTPException(404, "search not found")
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    await session.commit()
    return _ss_out(row)


@router.delete("/searches/{search_id}", status_code=204)
async def delete_search(
    search_id: str, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> None:
    row = await session.get(SavedSearch, search_id)
    if row is None or row.user_id != user.user_id:
        raise HTTPException(404, "search not found")
    await session.delete(row)
    await session.commit()


# ---- memory viewer ----
@router.get("/memory", response_model=MemoryView)
async def view_memory(user: CurrentUser) -> MemoryView:
    return MemoryView(**memstore.list_memory(user.user_id, runtime().store))


@router.delete("/memory/{kind}/{key}", status_code=204)
async def delete_memory(
    kind: str, key: str, user: CurrentUser, category: str | None = None
) -> None:
    if not memstore.delete_memory(user.user_id, kind, key, category, runtime().store):
        raise HTTPException(404, "memory item not found")


@router.delete("/memory", status_code=204)
async def clear_memory(user: CurrentUser) -> None:
    memstore.clear_memory(user.user_id, runtime().store)


# ---- connected accounts (OAuth 2.1 with PKCE for Upwork; GitHub PAT) ----
_PKCE: dict[str, dict[str, str]] = {}


@router.get("/accounts", response_model=list[ConnectedAccount])
async def accounts(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[ConnectedAccount]:
    rows = {
        r.provider: r
        for r in (
            await session.scalars(select(OAuthToken).where(OAuthToken.user_id == user.user_id))
        ).all()
    }
    out = [ConnectedAccount(provider="gigsim", connected=True, scopes="simulator")]
    for p in ("upwork", "github"):
        r = rows.get(p)
        out.append(
            ConnectedAccount(
                provider=p,
                connected=r is not None,
                scopes=r.scopes if r else "",
                expires_at=r.expires_at if r else None,
            )
        )
    return out


@router.post("/accounts/upwork/start")
async def upwork_start(user: CurrentUser) -> dict[str, str]:
    env = settings.env()
    if not env.upwork_oauth_client_id:
        raise HTTPException(
            400, "UPWORK_OAUTH_CLIENT_ID is not configured; live mode needs an Upwork OAuth app"
        )
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    state = secrets.token_urlsafe(16)
    _PKCE[state] = {"verifier": verifier, "user_id": user.user_id}
    params = {
        "response_type": "code",
        "client_id": env.upwork_oauth_client_id,
        "redirect_uri": env.upwork_oauth_redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return {
        "authorize_url": "https://www.upwork.com/ab/account-security/oauth2/authorize?"
        + urllib.parse.urlencode(params),
        "state": state,
    }


@router.get("/accounts/upwork/callback")
async def upwork_callback(
    code: str, state: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict[str, Any]:
    env = settings.env()
    pk = _PKCE.pop(state, None)
    if pk is None:
        raise HTTPException(400, "unknown or expired OAuth state")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://www.upwork.com/api/v3/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": env.upwork_oauth_redirect_uri,
                "client_id": env.upwork_oauth_client_id,
                "client_secret": env.upwork_oauth_client_secret,
                "code_verifier": pk["verifier"],
            },
        )
    if r.status_code != 200:
        raise HTTPException(502, "token exchange failed")
    tok = r.json()
    await save_oauth_token(session, pk["user_id"], "upwork", tok, scopes=tok.get("scope", ""))
    return {"connected": True}


@router.post("/accounts/github")
async def github_connect(
    body: dict[str, str], user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict[str, Any]:
    token = (body.get("token") or "").strip()
    if not token.startswith(("ghp_", "github_pat_")):
        raise HTTPException(400, "a GitHub personal access token is required")
    await save_oauth_token(
        session, user.user_id, "github", {"access_token": token}, scopes="repo:read"
    )
    return {"connected": True}


@router.delete("/accounts/{provider}", status_code=204)
async def disconnect(
    provider: str, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> None:
    if not await delete_oauth_token(session, user.user_id, provider):
        raise HTTPException(404, "not connected")
