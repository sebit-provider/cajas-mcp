from __future__ import annotations

import asyncio
import unittest

from cajas_mcp.config import Settings
from cajas_mcp.resources.capabilities import capabilities_payload
from cajas_mcp.security.policy import (
    COMMUNITY_VALIDATION_POLICY,
    EXPOSED_TOOL_NAMES,
    FORBIDDEN_MCP_ACTIONS,
    McpAction,
    assert_no_forbidden_tools,
    is_action_allowed,
)
from cajas_mcp.server import create_mcp_server


class CapabilityAndPolicyTests(unittest.TestCase):
    def test_capability_output_matches_phase(self) -> None:
        payload = capabilities_payload()
        self.assertTrue(payload["capabilities"]["raw_read"])
        self.assertTrue(payload["capabilities"]["event_read"])
        self.assertTrue(payload["capabilities"]["assembly_recommendation"])
        self.assertTrue(payload["capabilities"]["historical_assembly_context"])
        self.assertTrue(payload["capabilities"]["community_validation"])
        self.assertTrue(payload["capabilities"]["community_validation_opt_in_required"])
        self.assertFalse(payload["capabilities"]["community_validation_provider_stackexchange"])
        self.assertTrue(payload["capabilities"]["external_context_adapter"])
        self.assertFalse(payload["capabilities"]["external_context_search"])
        self.assertTrue(payload["capabilities"]["raw_file_inspection"])
        self.assertTrue(payload["capabilities"]["raw_import_preview"])
        self.assertTrue(payload["capabilities"]["raw_import"])
        self.assertTrue(payload["capabilities"]["coa_file_inspection"])
        self.assertTrue(payload["capabilities"]["coa_import_preview"])
        self.assertTrue(payload["capabilities"]["coa_import"])
        self.assertTrue(payload["capabilities"]["standard_reference_resolution"])
        self.assertTrue(payload["capabilities"]["criterion_search"])
        self.assertTrue(payload["capabilities"]["criterion_proposal"])
        self.assertFalse(payload["capabilities"]["criterion_creation"])
        self.assertTrue(payload["capabilities"]["interpretation_search"])
        self.assertTrue(payload["capabilities"]["interpretation_proposal"])
        self.assertFalse(payload["capabilities"]["interpretation_creation"])
        self.assertFalse(payload["capabilities"]["event_standard_link_mutation"])
        self.assertFalse(payload["capabilities"]["event_confirmation"])
        self.assertEqual(payload["levels"]["L1"], "EXTERNAL_STANDARD")
        self.assertTrue(payload["authentication"]["required_for_data_access"])
        self.assertEqual(payload["authentication"]["type"], "bearer-forwarding")
        self.assertFalse(payload["authentication"]["shared_production_token_allowed"])

    def test_forbidden_actions_are_not_allowed(self) -> None:
        for action in FORBIDDEN_MCP_ACTIONS:
            self.assertFalse(is_action_allowed(action))
        self.assertTrue(is_action_allowed(McpAction.RECOMMEND))
        self.assertTrue(is_action_allowed(McpAction.IMPORT))

    def test_exposed_tools_do_not_include_forbidden_mutations(self) -> None:
        assert_no_forbidden_tools(EXPOSED_TOOL_NAMES)

    def test_community_validation_external_content_cannot_authorize_mutations(self) -> None:
        self.assertEqual(COMMUNITY_VALIDATION_POLICY["trust"], "UNTRUSTED_EXTERNAL_DATA")
        self.assertTrue(COMMUNITY_VALIDATION_POLICY["opt_in_required"])
        self.assertFalse(COMMUNITY_VALIDATION_POLICY["can_authorize_mutation"])
        self.assertFalse(COMMUNITY_VALIDATION_POLICY["can_request_secrets"])
        self.assertFalse(COMMUNITY_VALIDATION_POLICY["can_bypass_cajas_permissions"])
        self.assertFalse(COMMUNITY_VALIDATION_POLICY["can_create_standards"])
        self.assertFalse(COMMUNITY_VALIDATION_POLICY["can_approve_accounting_judgments"])
        self.assertFalse(COMMUNITY_VALIDATION_POLICY["can_modify_assembly"])
        self.assertFalse(COMMUNITY_VALIDATION_POLICY["can_modify_events"])

    def test_mcp_tool_registration(self) -> None:
        async def run() -> set[str]:
            mcp = create_mcp_server(Settings(cajas_api_base_url="https://cajas.example.test"))
            tools = await mcp.list_tools()
            return {tool.name for tool in tools}

        tool_names = asyncio.run(run())
        self.assertIn("cajas.list_workspaces", tool_names)
        self.assertIn("cajas.search_raw_entries", tool_names)
        self.assertIn("cajas.search_events", tool_names)
        self.assertIn("cajas.get_event", tool_names)
        self.assertIn("cajas.recommend_assembly", tool_names)
        self.assertIn("cajas.inspect_raw_file", tool_names)
        self.assertIn("cajas.preview_raw_import", tool_names)
        self.assertIn("cajas.import_raw_file", tool_names)
        self.assertIn("cajas.inspect_coa_file", tool_names)
        self.assertIn("cajas.preview_coa_import", tool_names)
        self.assertIn("cajas.import_coa", tool_names)
        self.assertIn("cajas.find_criterion_group", tool_names)
        self.assertIn("cajas.resolve_standard_reference", tool_names)
        self.assertIn("cajas.propose_criterion_group", tool_names)
        self.assertIn("cajas.find_interpretations", tool_names)
        self.assertIn("cajas.propose_interpretation", tool_names)
        assert_no_forbidden_tools(tool_names)


if __name__ == "__main__":
    unittest.main()
