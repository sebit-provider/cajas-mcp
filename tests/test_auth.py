from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from cajas_mcp.auth import CajasTokenVerifier, token_binding
from cajas_mcp.config import Settings
from cajas_mcp.server import create_mcp_server


def _auth_settings() -> Settings:
    return Settings(
        cajas_api_base_url="https://cajas.example.test",
        public_url="https://sebit-mcp.com",
        auth_enabled=True,
        auth_issuer_url="https://auth.cajas.example.test",
        auth_resource_url="https://sebit-mcp.com/mcp",
        oauth_scopes_supported=("cajas:read",),
        oauth_required_scopes=("cajas:read",),
        allowed_hosts=("sebit-mcp.com", "localhost:*", "127.0.0.1:*"),
        allowed_origins=("https://sebit-mcp.com", "http://localhost:*"),
    )


class AuthTests(unittest.TestCase):
    def test_production_rejects_shared_environment_bearer(self) -> None:
        settings = Settings(
            env="production",
            cajas_api_base_url="https://cajas.example.test",
            cajas_api_bearer_token="shared-token",
        )
        with self.assertRaises(RuntimeError):
            settings.validate_startup()

    def test_auth_enabled_requires_issuer(self) -> None:
        settings = Settings(cajas_api_base_url="https://cajas.example.test", auth_enabled=True)
        with self.assertRaises(RuntimeError):
            settings.validate_startup()

    def test_unauthenticated_mcp_returns_www_authenticate_resource_metadata(self) -> None:
        mcp = create_mcp_server(_auth_settings())
        with TestClient(mcp.streamable_http_app()) as client:
            response = client.post(
                "/mcp",
                headers={"host": "sebit-mcp.com", "content-type": "application/json", "accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
        self.assertEqual(response.status_code, 401)
        www = response.headers.get("www-authenticate") or ""
        self.assertIn("Bearer", www)
        self.assertIn("resource_metadata=", www)
        self.assertIn("https://sebit-mcp.com/mcp/.well-known/oauth-protected-resource", www)

    def test_protected_resource_metadata_is_exposed(self) -> None:
        mcp = create_mcp_server(_auth_settings())
        with TestClient(mcp.streamable_http_app()) as client:
            response = client.get("/.well-known/oauth-protected-resource", headers={"host": "sebit-mcp.com"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resource"], "https://sebit-mcp.com/mcp")
        self.assertEqual(payload["authorization_servers"], ["https://auth.cajas.example.test/"])
        self.assertEqual(payload["scopes_supported"], ["cajas:read"])

    def test_protected_resource_metadata_aliases_are_exposed(self) -> None:
        mcp = create_mcp_server(_auth_settings())
        with TestClient(mcp.streamable_http_app()) as client:
            spec_response = client.get("/.well-known/oauth-protected-resource/mcp", headers={"host": "sebit-mcp.com"})
        self.assertEqual(spec_response.status_code, 200)
        self.assertEqual(spec_response.json()["resource"], "https://sebit-mcp.com/mcp")

    def test_valid_cajas_token_passes_mcp_auth_layer(self) -> None:
        mcp = create_mcp_server(_auth_settings())
        with patch("cajas_mcp.auth.CajasClient.get_me", new=AsyncMock(return_value={"me": {"user": {"id": "user-1"}}})):
            with patch("cajas_mcp.auth.CajasClient.aclose", new=AsyncMock()):
                with TestClient(mcp.streamable_http_app()) as client:
                    response = client.get(
                        "/mcp",
                        headers={
                            "host": "sebit-mcp.com",
                            "authorization": "Bearer valid-token",
                            "accept": "application/json",
                        },
                    )
        self.assertNotEqual(response.status_code, 401)

    def test_token_verifier_uses_cajas_identity(self) -> None:
        async def run():
            verifier = CajasTokenVerifier(_auth_settings())
            with patch("cajas_mcp.auth.CajasClient.get_me", new=AsyncMock(return_value={"me": {"user": {"id": "user-1"}}})):
                with patch("cajas_mcp.auth.CajasClient.aclose", new=AsyncMock()):
                    return await verifier.verify_token("valid-token")

        token = asyncio.run(run())
        self.assertIsNotNone(token)
        self.assertEqual(token.client_id, "user-1")
        self.assertEqual(token.resource, "https://sebit-mcp.com/mcp")

    def test_token_binding_is_stable_and_secret_sensitive(self) -> None:
        plain = token_binding(Settings(cajas_api_base_url="x"), "token-a")
        secret = token_binding(Settings(cajas_api_base_url="x", session_secret="secret"), "token-a")
        self.assertEqual(plain, token_binding(Settings(cajas_api_base_url="x"), "token-a"))
        self.assertNotEqual(plain, secret)


if __name__ == "__main__":
    unittest.main()
