from __future__ import annotations

from enum import StrEnum


class McpAction(StrEnum):
    READ = "READ"
    SEARCH = "SEARCH"
    INSPECT = "INSPECT"
    ANALYZE = "ANALYZE"
    PREVIEW = "PREVIEW"
    RECOMMEND = "RECOMMEND"
    PROPOSE = "PROPOSE"
    PREPARE = "PREPARE"
    IMPORT = "IMPORT"
    APPROVE = "APPROVE"
    SIGN = "SIGN"
    FINALIZE = "FINALIZE"
    CONFIRM_EVENT = "CONFIRM_EVENT"
    DELETE_CONFIRMED_EVENT = "DELETE_CONFIRMED_EVENT"
    MODIFY_IMMUTABLE_HISTORY = "MODIFY_IMMUTABLE_HISTORY"
    OVERRIDE_GOVERNANCE = "OVERRIDE_GOVERNANCE"


ALLOWED_MCP_ACTIONS: frozenset[McpAction] = frozenset(
    {
        McpAction.READ,
        McpAction.SEARCH,
        McpAction.INSPECT,
        McpAction.ANALYZE,
        McpAction.PREVIEW,
        McpAction.RECOMMEND,
        McpAction.PROPOSE,
        McpAction.PREPARE,
        McpAction.IMPORT,
    }
)

FORBIDDEN_MCP_ACTIONS: frozenset[McpAction] = frozenset(
    {
        McpAction.APPROVE,
        McpAction.SIGN,
        McpAction.FINALIZE,
        McpAction.CONFIRM_EVENT,
        McpAction.DELETE_CONFIRMED_EVENT,
        McpAction.MODIFY_IMMUTABLE_HISTORY,
        McpAction.OVERRIDE_GOVERNANCE,
    }
)

EXPOSED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "cajas.list_workspaces",
        "cajas.search_raw_entries",
        "cajas.search_events",
        "cajas.get_event",
        "cajas.recommend_assembly",
        "cajas.inspect_raw_file",
        "cajas.preview_raw_import",
        "cajas.import_raw_file",
        "cajas.inspect_coa_file",
        "cajas.preview_coa_import",
        "cajas.import_coa",
        "cajas.find_criterion_group",
        "cajas.resolve_standard_reference",
        "cajas.propose_criterion_group",
        "cajas.find_interpretations",
        "cajas.propose_interpretation",
    }
)

COMMUNITY_VALIDATION_POLICY: dict[str, bool | str] = {
    "trust": "UNTRUSTED_EXTERNAL_DATA",
    "opt_in_required": True,
    "can_authorize_mutation": False,
    "can_request_secrets": False,
    "can_bypass_cajas_permissions": False,
    "can_create_standards": False,
    "can_approve_accounting_judgments": False,
    "can_modify_assembly": False,
    "can_modify_events": False,
}


def is_action_allowed(action: McpAction | str) -> bool:
    parsed = McpAction(action)
    return parsed in ALLOWED_MCP_ACTIONS


def assert_no_forbidden_tools(tool_names: set[str] | frozenset[str]) -> None:
    forbidden_terms = ("approve", "sign", "finalize", "confirm", "delete_confirmed", "immutable_history")
    leaked = sorted(name for name in tool_names if any(term in name.lower() for term in forbidden_terms))
    if leaked:
        raise AssertionError(f"Forbidden MCP mutation tools exposed: {leaked}")
