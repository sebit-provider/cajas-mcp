from __future__ import annotations

from typing import Any

from cajas_mcp import __version__

PROTOCOL_VERSION = "2025-11-25"


def capabilities_payload(*, external_context_enabled: bool = False, auth_enabled: bool = False) -> dict[str, Any]:
    return {
        "name": "CAJAS MCP",
        "version": __version__,
        "protocol_version": PROTOCOL_VERSION,
        "capabilities": {
            "raw_read": True,
            "event_read": True,
            "assembly_recommendation": True,
            "historical_assembly_context": True,
            "governance_aware_history": True,
            "existing_assembly_comparison": True,
            "external_context_adapter": True,
            "external_context_search": external_context_enabled,
            "raw_file_inspection": True,
            "raw_import_preview": True,
            "raw_import": True,
            "coa_file_inspection": True,
            "coa_import_preview": True,
            "coa_import": True,
            "standard_reference_resolution": True,
            "criterion_search": True,
            "criterion_proposal": True,
            "criterion_creation": False,
            "interpretation_search": True,
            "interpretation_proposal": True,
            "interpretation_creation": False,
            "event_standard_link_mutation": False,
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
        "authentication": {
            "required_for_data_access": True,
            "type": "oauth-protected-resource" if auth_enabled else "bearer-forwarding",
            "shared_production_token_allowed": False,
        },
        "mutation_boundary": {
            "allowed": ["READ", "SEARCH", "INSPECT", "ANALYZE", "PREVIEW", "RECOMMEND", "PROPOSE", "PREPARE", "IMPORT"],
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
