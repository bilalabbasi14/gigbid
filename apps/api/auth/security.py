"""Passwords (Argon2), session tokens (JWT in an HttpOnly cookie) and the current-user dependency."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent import settings
from apps.api.db import User, get_session

_ph = PasswordHasher()
COOKIE = "gigbid_session"
ALGO = "HS256"


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except VerifyMismatchError:
        return False


def make_token(user_id: str, *, hours: int = 24 * 7) -> str:
    now = dt.datetime.now(dt.UTC)
    return jwt.encode(
        {"sub": user_id, "iat": now, "exp": now + dt.timedelta(hours=hours)},
        settings.env().app_secret_key,
        algorithm=ALGO,
    )


def read_token(token: str) -> str | None:
    try:
        return jwt.decode(token, settings.env().app_secret_key, algorithms=[ALGO])["sub"]
    except jwt.PyJWTError:
        return None


async def current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    gigbid_session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    token = gigbid_session
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    user_id = read_token(token) if token else None
    if not user_id:
        raise HTTPException(401, "not signed in")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(401, "unknown user")
    request.state.user_id = user.user_id
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email.lower().strip()))
