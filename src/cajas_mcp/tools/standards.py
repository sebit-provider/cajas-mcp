from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from cajas_mcp.adapters.standard_reference import DeterministicIFRSReferenceProvider, level_payload
from cajas_mcp.auth import resolve_bearer_token
from cajas_mcp.client import CajasClient
from cajas_mcp.config import Settings
from cajas_mcp.errors import CajasMcpError, error_payload, ok
from cajas_mcp.services_standards import (
    criterion_payload,
    find_existing_reference_match,
    interpretation_payload,
    propose_criterion_group_payload,
    propose_interpretation_payload,
)


def register_standard_tools(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="cajas.find_criterion_group",
        description="Searches existing CAJAS Criterion Groups in standards. This read-only tool does not create or modify standards.",
    )
    async def find_criterion_group(
        ctx: Context,
        org_id: str,
        query: str | None = None,
        standard_type: str | None = None,
        code: str | None = None,
        level: str | None = None,
        active_only: bool = True,
        limit: int = 20,
    ) -> dict:
        try:
            token = resolve_bearer_token(settings, ctx)
            client = CajasClient(settings)
            try:
                result = await client.list_standards(
                    token=token,
                    org_id=org_id,
                    filters={"query": query, "standard_type": standard_type, "code": code, "level": level, "active_only": active_only},
                )
            finally:
                await client.aclose()
            matches = [criterion_payload(row) for row in (result.get("items") or [])[: max(1, min(int(limit or 20), 100))]]
            return ok(
                {"matches": matches, "mutation": False},
                explanation="Returned existing CAJAS criterion groups without modifying standards.",
                request_id=result.get("_request_id"),
            )
        except CajasMcpError as exc:
            return error_payload(exc)

    @mcp.tool(
        name="cajas.resolve_standard_reference",
        description=(
            "Searches supported authoritative-reference locator sources for accounting standard reference candidates. "
            "It does not return or store full standard text and does not create CAJAS criterion groups."
        ),
    )
    async def resolve_standard_reference(
        ctx: Context,
        org_id: str,
        framework: str = "IFRS",
        query: str | None = None,
        event_context: dict[str, Any] | None = None,
    ) -> dict:
        try:
            resolve_bearer_token(settings, ctx)
            provider = DeterministicIFRSReferenceProvider()
            resolution = await provider.resolve(framework=framework, query=query or "", event_context=event_context)
            return ok(
                {"resolution": resolution, "mutation": False},
                explanation="Resolved standard reference locator candidates without returning full standard text.",
            )
        except CajasMcpError as exc:
            return error_payload(exc)

    @mcp.tool(
        name="cajas.propose_criterion_group",
        description=(
            "Creates a non-mutating CAJAS Criterion Group proposal from a resolved external reference. "
            "The proposed title and description are CAJAS-authored, not official standard headings."
        ),
    )
    async def propose_criterion_group(
        ctx: Context,
        org_id: str,
        reference_candidate: dict[str, Any],
        level: str = "L1",
    ) -> dict:
        try:
            token = resolve_bearer_token(settings, ctx)
            client = CajasClient(settings)
            try:
                existing = await client.list_standards(
                    token=token,
                    org_id=org_id,
                    filters={
                        "query": reference_candidate.get("reference_code"),
                        "standard_type": reference_candidate.get("framework"),
                        "active_only": True,
                    },
                )
            finally:
                await client.aclose()
            existing_match = find_existing_reference_match(
                existing.get("items") or [],
                str(reference_candidate.get("reference_code") or ""),
                str(reference_candidate.get("framework") or ""),
            )
            proposal = propose_criterion_group_payload(candidate=reference_candidate, existing_match=existing_match, requested_level=level)
            return ok(proposal, explanation="Prepared a non-mutating Criterion Group proposal.")
        except CajasMcpError as exc:
            return error_payload(exc)

    @mcp.tool(
        name="cajas.find_interpretations",
        description="Searches existing reusable CAJAS interpretations under a Criterion Group. This read-only tool does not create templates.",
    )
    async def find_interpretations(
        ctx: Context,
        org_id: str,
        criterion_group_id: str,
        query: str | None = None,
        level: str | None = None,
        limit: int = 20,
    ) -> dict:
        try:
            token = resolve_bearer_token(settings, ctx)
            client = CajasClient(settings)
            try:
                result = await client.find_interpretations(
                    token=token,
                    org_id=org_id,
                    group_id=criterion_group_id,
                    query=query,
                    limit=limit,
                )
            finally:
                await client.aclose()
            items = [interpretation_payload(row) for row in result.get("items") or []]
            if level:
                lv = str(level).upper()
                items = [item for item in items if item.get("interpretation_level", {}).get("code") == lv]
            return ok(
                {"criterion_group_id": criterion_group_id, "interpretations": items, "mutation": False},
                explanation="Returned existing reusable interpretations without modifying CAJAS.",
                request_id=result.get("_request_id"),
            )
        except CajasMcpError as exc:
            return error_payload(exc)

    @mcp.tool(
        name="cajas.propose_interpretation",
        description=(
            "Creates a non-mutating Interpretation proposal for a selected Criterion Group and judgment context. "
            "It does not create standard_templates, event_standard_links, approvals, or confirmations."
        ),
    )
    async def propose_interpretation(
        ctx: Context,
        org_id: str,
        criterion_group_id: str,
        event_context: dict[str, Any] | None = None,
        level: str | None = None,
        query: str | None = None,
    ) -> dict:
        try:
            token = resolve_bearer_token(settings, ctx)
            client = CajasClient(settings)
            try:
                group_result = await client.get_standard(token=token, org_id=org_id, standard_id=criterion_group_id)
                interp_result = await client.find_interpretations(
                    token=token,
                    org_id=org_id,
                    group_id=criterion_group_id,
                    query=query or _query_from_event_context(event_context),
                    limit=10,
                )
            finally:
                await client.aclose()
            group = criterion_payload(group_result.get("item") or {})
            similar = [interpretation_payload(row) for row in interp_result.get("items") or []]
            proposal = propose_interpretation_payload(
                criterion_group_id=criterion_group_id,
                criterion_group=group,
                event_context=event_context,
                requested_level=level,
                similar_existing=similar,
            )
            return ok(proposal, explanation="Prepared a non-mutating Interpretation proposal.")
        except CajasMcpError as exc:
            return error_payload(exc)


def _query_from_event_context(event_context: dict[str, Any] | None) -> str | None:
    if not isinstance(event_context, dict):
        return None
    for key in ("judgment_question", "summary", "title"):
        value = str(event_context.get(key) or "").strip()
        if value:
            return value[:120]
    return None
