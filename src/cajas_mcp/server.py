from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import __version__
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
    mcp = FastMCP(
        "cajas-mcp",
        instructions=SERVER_INSTRUCTIONS.strip(),
        json_response=True,
        stateless_http=False,
        streamable_http_path=settings.mcp_path,
        log_level=settings.log_level if settings.log_level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else "INFO",
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
        return capabilities_payload(external_context_enabled=settings.stackexchange_enabled)

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
