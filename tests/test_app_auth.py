from __future__ import annotations

import importlib
import os
import sys
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient


class AppAuthTests(unittest.TestCase):
    def test_production_app_serves_sdk_challenge_metadata_alias(self) -> None:
        env = {
            "CAJAS_API_BASE_URL": "https://cajas.example.test",
            "CAJAS_MCP_PUBLIC_URL": "https://sebit-mcp.com",
            "CAJAS_MCP_AUTH_ENABLED": "true",
            "CAJAS_MCP_AUTH_ISSUER_URL": "https://auth.cajas.example.test",
            "CAJAS_MCP_AUTH_RESOURCE_URL": "https://sebit-mcp.com/mcp",
        }
        with patch.dict(os.environ, env, clear=False):
            sys.modules.pop("cajas_mcp.app", None)
            app_module = importlib.import_module("cajas_mcp.app")
            try:
                with TestClient(app_module.app) as client:
                    root_response = client.get(
                        "/.well-known/oauth-protected-resource",
                        headers={"host": "sebit-mcp.com"},
                    )
                    spec_response = client.get(
                        "/.well-known/oauth-protected-resource/mcp",
                        headers={"host": "sebit-mcp.com"},
                    )
                    sdk_response = client.get(
                        "/mcp/.well-known/oauth-protected-resource",
                        headers={"host": "sebit-mcp.com"},
                    )
            finally:
                sys.modules.pop("cajas_mcp.app", None)

        for response in (root_response, spec_response, sdk_response):
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["resource"], "https://sebit-mcp.com/mcp")
            self.assertEqual(payload["authorization_servers"], ["https://auth.cajas.example.test"])
            self.assertEqual(
                payload["scopes_supported"],
                ["cajas:read", "cajas:raw:write", "cajas:coa:write", "cajas:criterion:read"],
            )


if __name__ == "__main__":
    unittest.main()
