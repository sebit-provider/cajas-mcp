from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

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

