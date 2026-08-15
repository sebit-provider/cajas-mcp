from __future__ import annotations

import hashlib
import hmac
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.auth.provider import AccessToken, TokenVerifier

from .client import CajasClient
from .config import Settings
from .errors import CajasMcpError


def _extract_authorization_from_context(ctx: Context | None) -> str | None:
    if ctx is None:
        return None
    request_context = getattr(ctx, "request_context", None)
    candidates: list[Any] = []
    if request_context is not None:
        candidates.extend(
            [
                getattr(request_context, "request", None),
                getattr(request_context, "meta", None),
                getattr(request_context, "request_meta", None),
            ]
        )
    for candidate in candidates:
        headers = getattr(candidate, "headers", None)
        if headers:
            value = headers.get("authorization") or headers.get("Authorization")
            if value:
                return str(value)
        if isinstance(candidate, dict):
            headers = candidate.get("headers") or {}
            if isinstance(headers, dict):
                value = headers.get("authorization") or headers.get("Authorization")
                if value:
                    return str(value)
    return None


def resolve_bearer_token(settings: Settings, ctx: Context | None = None, explicit_token: str | None = None) -> str:
    raw = explicit_token or _extract_authorization_from_context(ctx) or settings.cajas_api_bearer_token
    if not raw:
        raise CajasMcpError(
            "AUTH_REQUIRED",
            "CAJAS bearer token is required. Provide it through MCP HTTP Authorization or CAJAS_API_BEARER_TOKEN.",
            status_code=401,
            requires_user_action=True,
        )
    token = raw.strip()
    if token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1].strip()
    if not token:
        raise CajasMcpError("AUTH_REQUIRED", "Bearer token is empty.", status_code=401, requires_user_action=True)
    return token


def token_binding(settings: Settings, token: str) -> str:
    material = token.encode("utf-8")
    if settings.session_secret:
        digest = hmac.new(settings.session_secret.encode("utf-8"), material, hashlib.sha256).hexdigest()
    else:
        digest = hashlib.sha256(material).hexdigest()
    return f"tok_{digest[:32]}"


class CajasTokenVerifier(TokenVerifier):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None
        client = CajasClient(self.settings)
        try:
            result = await client.get_me(token=token)
        except CajasMcpError:
            return None
        finally:
            await client.aclose()
        payload = result.get("me") or {}
        user = payload.get("user") if isinstance(payload, dict) else {}
        user_id = str((user or {}).get("id") or (user or {}).get("email") or "cajas-user").strip()
        if not user_id:
            return None
        return AccessToken(
            token=token,
            client_id=user_id,
            scopes=list(self.settings.oauth_scopes_supported),
            resource=self.settings.auth_resource_url,
        )
