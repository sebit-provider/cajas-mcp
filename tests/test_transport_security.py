from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from cajas_mcp.config import Settings
from cajas_mcp.server import create_mcp_server


class TransportSecurityTests(unittest.TestCase):
    def test_default_allowed_hosts_include_localhost_and_public_host(self) -> None:
        settings = Settings.from_env()
        self.assertIn("localhost:*", settings.allowed_hosts)
        self.assertIn("127.0.0.1:*", settings.allowed_hosts)
        self.assertIn("sebit-mcp.com", settings.allowed_hosts)
        self.assertIn("https://sebit-mcp.com", settings.allowed_origins)

    def test_allowed_hosts_can_be_configured_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CAJAS_API_BASE_URL": "https://cajas.example.test",
                "CAJAS_MCP_ALLOWED_HOSTS": "sebit-mcp.com,localhost:*,127.0.0.1:*",
                "CAJAS_MCP_ALLOWED_ORIGINS": "https://sebit-mcp.com,http://localhost:*",
            },
            clear=False,
        ):
            settings = Settings.from_env()
        self.assertEqual(settings.allowed_hosts, ("sebit-mcp.com", "localhost:*", "127.0.0.1:*"))
        self.assertEqual(settings.allowed_origins, ("https://sebit-mcp.com", "http://localhost:*"))

    def test_mcp_rejects_unknown_host_header(self) -> None:
        mcp = create_mcp_server(
            Settings(
                cajas_api_base_url="https://cajas.example.test",
                allowed_hosts=("sebit-mcp.com", "localhost:*", "127.0.0.1:*"),
                allowed_origins=("https://sebit-mcp.com", "http://localhost:*"),
            )
        )
        with TestClient(mcp.streamable_http_app()) as client:
            response = client.get("/mcp", headers={"host": "evil.example"})
        self.assertEqual(response.status_code, 421)
        self.assertEqual(response.text, "Invalid Host header")

    def test_mcp_accepts_canonical_host_before_protocol_validation(self) -> None:
        mcp = create_mcp_server(
            Settings(
                cajas_api_base_url="https://cajas.example.test",
                allowed_hosts=("sebit-mcp.com", "localhost:*", "127.0.0.1:*"),
                allowed_origins=("https://sebit-mcp.com", "http://localhost:*"),
            )
        )
        with TestClient(mcp.streamable_http_app()) as client:
            response = client.get("/mcp", headers={"host": "sebit-mcp.com"})
        self.assertNotEqual(response.status_code, 421)
        self.assertNotEqual(response.text, "Invalid Host header")

    def test_mcp_rejects_unknown_origin_header(self) -> None:
        mcp = create_mcp_server(
            Settings(
                cajas_api_base_url="https://cajas.example.test",
                allowed_hosts=("sebit-mcp.com", "localhost:*", "127.0.0.1:*"),
                allowed_origins=("https://sebit-mcp.com", "http://localhost:*"),
            )
        )
        with TestClient(mcp.streamable_http_app()) as client:
            response = client.get(
                "/mcp",
                headers={
                    "host": "sebit-mcp.com",
                    "origin": "https://evil.example",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.text, "Invalid Origin header")


if __name__ == "__main__":
    unittest.main()
