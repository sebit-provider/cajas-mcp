from __future__ import annotations

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import __version__
from .auth import CajasTokenVerifier
from .config import Settings
from .resources.capabilities import capabilities_payload
from .security.policy import EXPOSED_TOOL_NAMES, assert_no_forbidden_tools
from .tools.assembly import register_assembly_tools
from .tools.coa import register_coa_tools
from .tools.events import register_event_tools
from .tools.import_raw import register_import_raw_tools
from .tools.raw import register_raw_tools
from .tools.standards import register_standard_tools
from .tools.workspace import register_workspace_tools


SERVER_INSTRUCTIONS = """
CAJAS MCP exposes vendor-neutral tools over the authenticated CAJAS API.
Read, search, RAW/CoA file import, Assembly recommendation, and Criterion/Interpretation proposal tools are available.
Recommendations are non-binding and never approve, sign, finalize, confirm, or alter immutable accounting history.
"""


def create_mcp_server(settings: Settings | None = None) -> FastMCP:
    settings = settings or Settings.from_env()
    settings.validate_startup()
    auth_settings = (
        AuthSettings(
            issuer_url=settings.auth_issuer_url,
            resource_server_url=settings.auth_resource_url,
            required_scopes=list(settings.oauth_required_scopes),
            service_documentation_url=settings.public_url,
        )
        if settings.auth_enabled
        else None
    )
    mcp = FastMCP(
        "cajas-mcp",
        instructions=SERVER_INSTRUCTIONS.strip(),
        json_response=True,
        stateless_http=False,
        streamable_http_path=settings.mcp_path,
        log_level=settings.log_level if settings.log_level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else "INFO",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(settings.allowed_hosts),
            allowed_origins=list(settings.allowed_origins),
        ),
        auth=auth_settings,
        token_verifier=CajasTokenVerifier(settings) if settings.auth_enabled else None,
    )

    register_workspace_tools(mcp, settings)
    register_raw_tools(mcp, settings)
    register_event_tools(mcp, settings)
    register_assembly_tools(mcp, settings)
    register_import_raw_tools(mcp, settings)
    register_coa_tools(mcp, settings)
    register_standard_tools(mcp, settings)

    @mcp.resource("cajas://capabilities", name="CAJAS MCP Capabilities")
    def capabilities() -> dict:
        return capabilities_payload(external_context_enabled=settings.stackexchange_enabled, auth_enabled=settings.auth_enabled)

    if settings.auth_enabled:
        metadata_payload = {
            "resource": settings.auth_resource_url,
            "authorization_servers": [settings.auth_issuer_url],
            "scopes_supported": list(settings.oauth_scopes_supported),
            "resource_name": "CAJAS MCP",
            "resource_documentation": settings.public_url,
        }

        @mcp.custom_route("/.well-known/oauth-protected-resource/mcp", methods=["GET", "OPTIONS"], include_in_schema=False)
        async def protected_resource_metadata_for_mcp_path(request: Request) -> Response:
            return JSONResponse(metadata_payload)

        @mcp.custom_route("/mcp/.well-known/oauth-protected-resource", methods=["GET", "OPTIONS"], include_in_schema=False)
        async def protected_resource_metadata_for_sdk_challenge(request: Request) -> Response:
            return JSONResponse(metadata_payload)

    assert_no_forbidden_tools(EXPOSED_TOOL_NAMES)
    return mcp


def main() -> None:
    settings = Settings.from_env()
    mcp = create_mcp_server(settings)
    transport = settings.transport.lower()
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http")


__all__ = ["create_mcp_server", "main", "__version__"]
