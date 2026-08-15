from mcp.server.fastmcp import Context, FastMCP

from cajas_mcp.auth import resolve_bearer_token
from cajas_mcp.client import CajasClient
from cajas_mcp.config import Settings
from cajas_mcp.errors import CajasMcpError, error_payload, ok


def register_raw_tools(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="cajas.search_raw_entries",
        description=(
            "Searches CAJAS RAW entries with pagination and filters. "
            "Supported status values are draft, queued, assembled, and voided. "
            "project and department are returned only when stored by CAJAS; missing values are not inferred. "
            "created_by_name is a stored actor label and may differ from created_by_display profile identity. "
            "This read-only tool does not modify RAW status, create an Assembly, or create an Event."
        ),
    )
    async def search_raw_entries(
        ctx: Context,
        org_id: str,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        coa_profile_id: str | None = None,
        project: str | None = None,
        department: str | None = None,
        counterparty_id: str | None = None,
        query: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict:
        try:
            token = resolve_bearer_token(settings, ctx)
            filters = {
                "status": status,
                "date_from": date_from,
                "date_to": date_to,
                "coa_profile_id": coa_profile_id,
                "project": project,
                "department": department,
                "counterparty_id": counterparty_id,
                "query": query,
                "limit": max(1, min(int(limit), 200)),
                "cursor": cursor,
            }
            client = CajasClient(settings)
            try:
                result = await client.search_raw_entries(token=token, org_id=org_id, filters=filters)
            finally:
                await client.aclose()
            return ok(
                {"raw_entries": result["raw_entries"], "next_cursor": result["next_cursor"]},
                explanation="Returned matching RAW entries without modifying CAJAS state.",
                request_id=result.get("_request_id"),
            )
        except CajasMcpError as exc:
            return error_payload(exc)
