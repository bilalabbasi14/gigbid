"""Encrypted OAuth token store (E4): tokens are Fernet-encrypted at rest with TOKEN_ENCRYPTION_KEY,
scoped per user and provider, and never logged."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent import settings
from apps.api.db import OAuthToken, session_factory


def _fernet() -> Fernet:
    key = settings.env().token_encryption_key
    if not key:
        # derive a stable dev key from the app secret so local runs work; production sets a real key
        key = base64.urlsafe_b64encode(
            hashlib.sha256(settings.env().app_secret_key.encode()).digest()
        ).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(payload: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(payload).encode()).decode()


def decrypt(blob: str) -> dict[str, Any]:
    return json.loads(_fernet().decrypt(blob.encode()).decode())


async def save_oauth_token(
    session: AsyncSession,
    user_id: str,
    provider: str,
    payload: dict[str, Any],
    *,
    scopes: str = "",
    expires_at: dt.datetime | None = None,
) -> None:
    row = await session.scalar(
        select(OAuthToken).where(OAuthToken.user_id == user_id, OAuthToken.provider == provider)
    )
    if row is None:
        row = OAuthToken(user_id=user_id, provider=provider, encrypted="")
        session.add(row)
    row.encrypted = encrypt(payload)
    row.scopes = scopes
    row.expires_at = expires_at
    await session.commit()


async def get_oauth_token(
    session: AsyncSession, user_id: str, provider: str
) -> dict[str, Any] | None:
    row = await session.scalar(
        select(OAuthToken).where(OAuthToken.user_id == user_id, OAuthToken.provider == provider)
    )
    return decrypt(row.encrypted) if row else None


async def delete_oauth_token(session: AsyncSession, user_id: str, provider: str) -> bool:
    row = await session.scalar(
        select(OAuthToken).where(OAuthToken.user_id == user_id, OAuthToken.provider == provider)
    )
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


def load_oauth_token(user_id: str, provider: str) -> str | None:
    """Sync helper for adapters constructed outside a request: returns the access token or None."""
    import asyncio

    async def _go() -> str | None:
        async with session_factory()() as s:
            tok = await get_oauth_token(s, user_id, provider)
            return tok.get("access_token") if tok else None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_go())
    if loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            return ex.submit(lambda: asyncio.run(_go())).result()
    return asyncio.run(_go())
