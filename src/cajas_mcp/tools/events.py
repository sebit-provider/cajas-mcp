from mcp.server.fastmcp import Context, FastMCP

from cajas_mcp.auth import resolve_bearer_token
from cajas_mcp.client import CajasClient
from cajas_mcp.config import Settings
from cajas_mcp.errors import CajasMcpError, error_payload, ok


def register_event_tools(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="cajas.search_events",
        description=(
            "Searches CAJAS accounting events. "
            "This read-only tool does not confirm, void, sign, approve, finalize, or alter events."
        ),
    )
    async def search_events(
        ctx: Context,
        org_id: str,
        state: str | None = None,
        query: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict:
        try:
            token = resolve_bearer_token(settings, ctx)
            filters = {"state": state, "query": query, "limit": max(1, min(int(limit), 100)), "cursor": cursor}
            client = CajasClient(settings)
            try:
                result = await client.search_events(token=token, org_id=org_id, filters=filters)
            finally:
                await client.aclose()
            return ok(
                {"events": result["events"], "next_cursor": result["next_cursor"]},
                explanation="Returned matching accounting events without modifying CAJAS state.",
                request_id=result.get("_request_id"),
            )
        except CajasMcpError as exc:
            return error_payload(exc)

    @mcp.tool(
        name="cajas.get_event",
        description=(
            "Returns one CAJAS accounting event and CAJAS-provided judgment support context. "
            "This read-only tool does not confirm, void, sign, approve, finalize, or alter the event."
        ),
    )
    async def get_event(ctx: Context, org_id: str, event_id: str) -> dict:
        try:
            token = resolve_bearer_token(settings, ctx)
            client = CajasClient(settings)
            try:
                result = await client.get_event(token=token, org_id=org_id, event_id=event_id)
            finally:
                await client.aclose()
            return ok(
                {"event": result["event"]},
                explanation="Returned event detail without modifying CAJAS state.",
                request_id=result.get("_request_id"),
            )
        except CajasMcpError as exc:
            return error_payload(exc)
