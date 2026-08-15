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


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/ready", ready, methods=["GET"]),
        Route("/version", version, methods=["GET"]),
        Mount("/", app=mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)

app = CORSMiddleware(
    app,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "MCP-Protocol-Version", "Mcp-Session-Id"],
    expose_headers=["Mcp-Session-Id"],
)

