from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from cajas_mcp.adapters.external_context import DisabledExternalContextProvider
from cajas_mcp.adapters.stack_exchange import StackExchangeProvider
from cajas_mcp.auth import resolve_bearer_token
from cajas_mcp.client import CajasClient
from cajas_mcp.config import Settings
from cajas_mcp.errors import CajasMcpError, error_payload, ok
from cajas_mcp.services import AssemblyRecommendationEngine


def _external_provider(settings: Settings):
    if not settings.stackexchange_enabled:
        return DisabledExternalContextProvider()
    return StackExchangeProvider(
        site=settings.stackexchange_site,
        key=settings.stackexchange_key,
        timeout=settings.external_timeout,
    )


def register_assembly_tools(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="cajas.recommend_assembly",
        description=(
            "Analyzes selected RAW entries and returns non-binding Assembly candidates for human review. "
            "The recommendation identifies RAW entries that may share an operational context. "
            "It does not create an Assembly, modify RAW status, create an Event, determine accounting treatment, "
            "approve accounting judgment, sign, finalize, or alter immutable CAJAS history."
        ),
    )
    async def recommend_assembly(
        ctx: Context,
        org_id: str,
        raw_entry_ids: list[str],
        include_external_context: bool = False,
    ) -> dict:
        try:
            unique_ids = []
            seen = set()
            for raw_id in raw_entry_ids:
                clean = str(raw_id or "").strip()
                if clean and clean not in seen:
                    seen.add(clean)
                    unique_ids.append(clean)
            if not unique_ids:
                raise CajasMcpError("INVALID_INPUT", "raw_entry_ids must contain at least one id.", requires_user_action=True)
            if len(unique_ids) > settings.max_recommendation_raw_entries:
                raise CajasMcpError(
                    "INVALID_INPUT",
                    f"Too many RAW entries for one recommendation request. Limit is {settings.max_recommendation_raw_entries}.",
                    requires_user_action=True,
                    details={"limit": settings.max_recommendation_raw_entries},
                )
            token = resolve_bearer_token(settings, ctx)
            client = CajasClient(settings)
            try:
                raw_entries = []
                request_id = None
                for raw_id in unique_ids:
                    result = await client.get_raw_entry(token=token, org_id=org_id, raw_entry_id=raw_id)
                    request_id = request_id or result.get("_request_id")
                    raw_entries.append(result["raw_entry"])
            finally:
                await client.aclose()

            provider = _external_provider(settings)
            engine = AssemblyRecommendationEngine(external_provider=provider)
            result = await engine.recommend(raw_entries, include_external_context=include_external_context)
            if hasattr(provider, "aclose"):
                await provider.aclose()
            return ok(
                result,
                explanation="Returned non-binding Assembly recommendations. No CAJAS state was modified.",
                warnings=[
                    "Assembly recommendations are suggestions for review and do not determine accounting treatment.",
                ],
                request_id=request_id,
            )
        except CajasMcpError as exc:
            return error_payload(exc)

