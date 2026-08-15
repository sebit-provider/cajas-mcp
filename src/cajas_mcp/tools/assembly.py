from mcp.server.fastmcp import Context, FastMCP

from cajas_mcp.adapters.external_context import DisabledExternalContextProvider
from cajas_mcp.adapters.stack_exchange import StackExchangeProvider
from cajas_mcp.auth import resolve_bearer_token
from cajas_mcp.client import CajasClient
from cajas_mcp.community_validation import CommunityValidationService, parse_community_validation
from cajas_mcp.config import Settings
from cajas_mcp.errors import CajasMcpError, error_payload, ok
from cajas_mcp.schemas.raw import RawEntry
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
            "Community validation is opt-in only and uses public, untrusted operational context when requested. "
            "It does not create an Assembly, modify RAW status, create an Event, determine accounting treatment, "
            "approve accounting judgment, sign, finalize, or alter immutable CAJAS history."
        ),
    )
    async def recommend_assembly(
        ctx: Context,
        org_id: str,
        raw_entry_ids: list[str],
        include_external_context: bool = False,
        community_validation: dict | None = None,
        community_validation_enabled: bool = False,
        community_validation_mode: str = "BALANCED",
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
                try:
                    history_result = await client.list_assembly_history(
                        token=token,
                        org_id=org_id,
                        filters=_history_filters_from_raw_entries(raw_entries),
                    )
                    request_id = request_id or history_result.get("_request_id")
                except CajasMcpError as history_error:
                    history_result = {
                        "items": [],
                        "history_available": False,
                        "history_warning": history_error.code,
                    }
            finally:
                await client.aclose()

            provider = _external_provider(settings)
            engine = AssemblyRecommendationEngine(external_provider=provider)
            result = await engine.recommend(
                raw_entries,
                include_external_context=include_external_context,
                historical_groups=history_result.get("items") or [],
                history_available=bool(history_result.get("history_available", False)),
            )
            validation_request = parse_community_validation(
                community_validation,
                enabled=community_validation_enabled,
                mode=community_validation_mode,
            )
            validation_service = CommunityValidationService(
                provider,
                provider_enabled=bool(settings.stackexchange_enabled),
                cache_ttl=settings.external_cache_ttl,
            )
            result["community_validation"] = await validation_service.validate(
                request=validation_request,
                raw_entries=[RawEntry.model_validate(row) for row in raw_entries],
                recommendations=list(result.get("candidates") or []),
            )
            if hasattr(provider, "aclose"):
                await provider.aclose()
            return ok(
                result,
                explanation="Returned non-binding Assembly recommendations. No CAJAS state was modified.",
                warnings=[
                    "Assembly recommendations are suggestions for review and do not determine accounting treatment.",
                    *(
                        [f"Historical assembly context unavailable: {history_result.get('history_warning')}"]
                        if history_result.get("history_warning")
                        else []
                    ),
                ],
                request_id=request_id,
            )
        except CajasMcpError as exc:
            return error_payload(exc)


def _history_filters_from_raw_entries(raw_entries: list[dict]) -> dict:
    filters: dict = {"limit": 100}
    if not raw_entries:
        return filters

    def common_value(*keys: str) -> str | None:
        values = set()
        for row in raw_entries:
            value = ""
            for key in keys:
                value = str(row.get(key) or "").strip()
                if value:
                    break
            if value:
                values.add(value)
        return next(iter(values)) if len(values) == 1 else None

    project = common_value("project")
    department = common_value("department")
    counterparty_id = common_value("counterparty_id", "counterpart_id")
    if project:
        filters["project"] = project
    if department:
        filters["department"] = department
    if counterparty_id:
        filters["counterparty_id"] = counterparty_id
    return filters
