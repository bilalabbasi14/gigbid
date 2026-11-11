"""Bearer-token auth for our own HTTP MCP endpoints.

Tokens are static per deployment (MCP_BEARER_TOKEN) with optional per-user tokens in
MCP_USER_TOKENS="token1:user1,token2:user2". The verifier maps a token to a user id so the
marketplace server can rate-limit and audit per user.
"""

from __future__ import annotations

import hmac
import logging
import os

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

log = logging.getLogger(__name__)


def _token_map() -> dict[str, str]:
    tokens: dict[str, str] = {}
    base = os.environ.get("MCP_BEARER_TOKEN", "")
    if base:
        tokens[base] = "service"
    for item in os.environ.get("MCP_USER_TOKENS", "").split(","):
        if ":" in item:
            tok, user = item.split(":", 1)
            tokens[tok.strip()] = user.strip()
    return tokens


class StaticTokenVerifier(TokenVerifier):
    def __init__(self, tokens: dict[str, str] | None = None) -> None:
        self.tokens = tokens if tokens is not None else _token_map()

    async def verify_token(self, token: str) -> AccessToken | None:
        for known, user in self.tokens.items():
            if hmac.compare_digest(known, token):
                return AccessToken(
                    token=token,
                    client_id=user,
                    scopes=[
                        "portfolio:read",
                        "marketplace:read",
                        "marketplace:write",
                        "workspace:write",
                    ],
                    subject=user,
                )
        return None


def make_token_verifier() -> TokenVerifier:
    return StaticTokenVerifier()


def token_auth_settings() -> AuthSettings:
    base = os.environ.get("APP_BASE_URL", "http://localhost:8000")
    return AuthSettings(
        issuer_url=AnyHttpUrl(base), resource_server_url=AnyHttpUrl(base), required_scopes=[]
    )


def user_from_context(ctx) -> str:  # type: ignore[no-untyped-def]
    """Resolve the calling user: bearer token subject when served over HTTP, else 'local'."""
    try:
        rc = ctx.request_context
        req = getattr(rc, "request", None)
        user = getattr(getattr(req, "user", None), "username", None) if req is not None else None
        if user:
            return str(user)
        token = (
            getattr(getattr(req, "state", None), "access_token", None) if req is not None else None
        )
        if token is not None and getattr(token, "subject", None):
            return str(token.subject)
    except Exception as exc:  # noqa: BLE001
        log.debug("no user in MCP context: %s", exc)
    return "local"
