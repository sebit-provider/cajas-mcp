from __future__ import annotations

from typing import Any

from cajas_mcp import __version__

PROTOCOL_VERSION = "2025-11-25"


def capabilities_payload(*, external_context_enabled: bool = False) -> dict[str, Any]:
    return {
        "name": "CAJAS MCP",
        "version": __version__,
        "protocol_version": PROTOCOL_VERSION,
        "capabilities": {
            "raw_read": True,
            "event_read": True,
            "assembly_recommendation": True,
            "external_context_adapter": True,
            "external_context_search": external_context_enabled,
            "raw_import": False,
            "coa_import": False,
            "standard_reference_resolution": False,
            "event_confirmation": False,
            "approval": False,
            "signature": False,
            "immutable_history_mutation": False,
        },
        "levels": {
            "L1": "EXTERNAL_STANDARD",
            "L2": "INTERNAL_POLICY",
            "L3": "TEMPORARY_OR_SUBJECTIVE",
        },
        "mutation_boundary": {
            "allowed": ["READ", "SEARCH", "INSPECT", "ANALYZE", "PREVIEW", "RECOMMEND", "PROPOSE", "PREPARE"],
            "not_exposed": [
                "FINAL_ACCOUNTING_APPROVAL",
                "SIGNATURE",
                "FINALIZE_ASSEMBLY",
                "CONFIRM_EVENT",
                "OVERRIDE_GOVERNANCE",
                "DELETE_CONFIRMED_EVENT",
                "MODIFY_IMMUTABLE_HISTORY",
            ],
        },
    }
