from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from agent import settings
from apps.api.auth.security import (
    COOKIE,
    CurrentUser,
    get_user_by_email,
    hash_password,
    make_token,
    verify_password,
)
from apps.api.db import User, get_session
from apps.api.schemas import LoginIn, RegisterIn, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(u: User) -> UserOut:
    st = dict(u.settings_json or {})
    return UserOut(
        user_id=u.user_id,
        email=u.email,
        display_name=u.display_name,
        role=u.role,
        persona=u.persona,
        onboarded=bool(st.get("onboarded")),
        settings=st,
    )


def _set_cookie(resp: Response, token: str) -> None:
    secure = settings.env().app_env == "production"
    resp.set_cookie(
        COOKIE, token, httponly=True, samesite="lax", secure=secure, max_age=7 * 24 * 3600, path="/"
    )


@router.post("/register", response_model=UserOut, status_code=201)
async def register(
    body: RegisterIn, response: Response, session: Annotated[AsyncSession, Depends(get_session)]
) -> UserOut:
    if await get_user_by_email(session, body.email):
        raise HTTPException(409, "email already registered")
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        display_name=body.display_name or body.email.split("@")[0],
        persona=body.persona,
        settings_json={
            "persona": body.persona,
            "autonomy": "auto_skip",
            "weekly_connects_budget": 80,
        },
    )
    session.add(user)
    await session.commit()
    _set_cookie(response, make_token(user.user_id))
    return user_out(user)


@router.post("/login", response_model=UserOut)
async def login(
    body: LoginIn, response: Response, session: Annotated[AsyncSession, Depends(get_session)]
) -> UserOut:
    user = await get_user_by_email(session, body.email)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "invalid email or password")
    _set_cookie(response, make_token(user.user_id))
    return user_out(user)


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return user_out(user)
