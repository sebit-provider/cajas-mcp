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
    }
)


def is_action_allowed(action: McpAction | str) -> bool:
    parsed = McpAction(action)
    return parsed in ALLOWED_MCP_ACTIONS


def assert_no_forbidden_tools(tool_names: set[str] | frozenset[str]) -> None:
    forbidden_terms = ("approve", "sign", "finalize", "confirm", "delete_confirmed", "immutable_history")
    leaked = sorted(name for name in tool_names if any(term in name.lower() for term in forbidden_terms))
    if leaked:
        raise AssertionError(f"Forbidden MCP mutation tools exposed: {leaked}")

