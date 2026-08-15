from __future__ import annotations

import contextlib
from typing import Any

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from . import __version__
from .config import Settings
from .resources.capabilities import PROTOCOL_VERSION
from .server import create_mcp_server

settings = Settings.from_env()
mcp = create_mcp_server(settings)


async def root(_: Any) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "cajas-mcp", "health": "/health", "mcp": settings.mcp_path})


async def health(_: Any) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "cajas-mcp", "version": __version__})


async def ready(_: Any) -> JSONResponse:
    missing = settings.validate_ready()
    status = 200 if not missing else 503
    return JSONResponse({"ok": not missing, "missing": missing}, status_code=status)


async def version(_: Any) -> JSONResponse:
    return JSONResponse(
        {
            "name": "cajas-mcp",
            "version": __version__,
            "protocol_version": PROTOCOL_VERSION,
            "mcp_path": settings.mcp_path,
        }
    )


@contextlib.asynccontextmanager
async def lifespan(_: Starlette):
    async with mcp.session_manager.run():
        yield


routes = [
    Route("/", root, methods=["GET"]),
    Route("/health", health, methods=["GET"]),
    Route("/api/health", health, methods=["GET"]),
    Route("/ready", ready, methods=["GET"]),
    Route("/version", version, methods=["GET"]),
]

if settings.auth_enabled:
    metadata_payload = {
        "resource": settings.auth_resource_url,
        "authorization_servers": [settings.auth_issuer_url],
        "scopes_supported": list(settings.oauth_scopes_supported),
        "resource_name": "CAJAS MCP",
        "resource_documentation": settings.public_url,
    }

    async def protected_resource_metadata(_: Any) -> JSONResponse:
        return JSONResponse(metadata_payload)

    routes.extend(
        [
            Route("/.well-known/oauth-protected-resource", protected_resource_metadata, methods=["GET", "OPTIONS"]),
            Route("/.well-known/oauth-protected-resource/mcp", protected_resource_metadata, methods=["GET", "OPTIONS"]),
            Route("/mcp/.well-known/oauth-protected-resource", protected_resource_metadata, methods=["GET", "OPTIONS"]),
        ]
    )

routes.append(Mount("/", app=mcp.streamable_http_app()))

app = Starlette(
    routes=routes,
    lifespan=lifespan,
)

app = CORSMiddleware(
    app,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "MCP-Protocol-Version", "Mcp-Session-Id"],
    expose_headers=["Mcp-Session-Id"],
)
