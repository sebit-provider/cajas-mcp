from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from cajas_mcp.auth import resolve_bearer_token
from cajas_mcp.client import CajasClient
from cajas_mcp.config import Settings
from cajas_mcp.errors import CajasMcpError, error_payload, ok


def register_workspace_tools(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="cajas.list_workspaces",
        description=(
            "Lists CAJAS workspaces/orgs available to the authenticated user. "
            "This read-only tool does not create, archive, restore, or switch workspaces."
        ),
    )
    async def list_workspaces(ctx: Context, include_archived: bool = False) -> dict:
        try:
            token = resolve_bearer_token(settings, ctx)
            client = CajasClient(settings)
            try:
                result = await client.list_workspaces(token=token, include_archived=include_archived)
            finally:
                await client.aclose()
            return ok(
                {"workspaces": result["workspaces"]},
                explanation="Returned CAJAS workspaces visible to the authenticated user.",
                request_id=result.get("_request_id"),
            )
        except CajasMcpError as exc:
            return error_payload(exc)

