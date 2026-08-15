from __future__ import annotations

import asyncio
import unittest

from cajas_mcp.config import Settings
from cajas_mcp.resources.capabilities import capabilities_payload
from cajas_mcp.security.policy import EXPOSED_TOOL_NAMES, FORBIDDEN_MCP_ACTIONS, McpAction, assert_no_forbidden_tools, is_action_allowed
from cajas_mcp.server import create_mcp_server


class CapabilityAndPolicyTests(unittest.TestCase):
    def test_capability_output_matches_phase(self) -> None:
        payload = capabilities_payload()
        self.assertTrue(payload["capabilities"]["raw_read"])
        self.assertTrue(payload["capabilities"]["event_read"])
        self.assertTrue(payload["capabilities"]["assembly_recommendation"])
        self.assertTrue(payload["capabilities"]["external_context_adapter"])
        self.assertFalse(payload["capabilities"]["external_context_search"])
        self.assertFalse(payload["capabilities"]["raw_import"])
        self.assertFalse(payload["capabilities"]["coa_import"])
        self.assertFalse(payload["capabilities"]["event_confirmation"])
        self.assertEqual(payload["levels"]["L1"], "EXTERNAL_STANDARD")

    def test_forbidden_actions_are_not_allowed(self) -> None:
        for action in FORBIDDEN_MCP_ACTIONS:
            self.assertFalse(is_action_allowed(action))
        self.assertTrue(is_action_allowed(McpAction.RECOMMEND))

    def test_exposed_tools_do_not_include_forbidden_mutations(self) -> None:
        assert_no_forbidden_tools(EXPOSED_TOOL_NAMES)

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
        assert_no_forbidden_tools(tool_names)


if __name__ == "__main__":
    unittest.main()
