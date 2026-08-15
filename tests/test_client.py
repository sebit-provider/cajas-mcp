from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from cajas_mcp.client import CajasClient
from cajas_mcp.config import Settings
from cajas_mcp.errors import CajasMcpError


def _settings() -> Settings:
    return Settings(cajas_api_base_url="https://cajas.example.test", http_retries=0)


class CajasClientTests(unittest.TestCase):
    def test_token_and_org_forwarding(self) -> None:
        seen: dict[str, str | None] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["authorization"] = request.headers.get("authorization")
            seen["org"] = request.headers.get("x-org-id")
            seen["request_id"] = request.headers.get("x-request-id")
            return httpx.Response(200, json={"ok": True, "items": {"items": [{"id": "raw_1"}], "count_summary": {"total": 1}}})

        async def run() -> dict:
            client = CajasClient(_settings(), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://cajas.example.test"))
            try:
                return await client.search_raw_entries(token="token-1", org_id="org-1", filters={"limit": 10})
            finally:
                await client.aclose()

        result = asyncio.run(run())
        self.assertEqual(seen["authorization"], "Bearer token-1")
        self.assertEqual(seen["org"], "org-1")
        self.assertTrue(str(seen["request_id"]).startswith("mcp_"))
        self.assertEqual(result["raw_entries"][0]["id"], "raw_1")

    def test_401_normalization(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "invalid token"})

        async def run() -> None:
            client = CajasClient(_settings(), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://cajas.example.test"))
            try:
                await client.list_workspaces(token="bad")
            finally:
                await client.aclose()

        with self.assertRaises(CajasMcpError) as caught:
            asyncio.run(run())
        self.assertEqual(caught.exception.code, "AUTH_REQUIRED")
        self.assertTrue(caught.exception.requires_user_action)

    def test_403_404_5xx_normalization(self) -> None:
        cases = [(403, "PERMISSION_DENIED"), (404, "RESOURCE_NOT_FOUND"), (503, "CAJAS_API_UNAVAILABLE")]
        for status, code in cases:
            with self.subTest(status=status):
                def handler(_: httpx.Request, status: int = status) -> httpx.Response:
                    return httpx.Response(status, content=json.dumps({"detail": "failure"}))

                async def run() -> None:
                    client = CajasClient(_settings(), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://cajas.example.test"))
                    try:
                        await client.get_event(token="t", org_id="org", event_id="evt")
                    finally:
                        await client.aclose()

                with self.assertRaises(CajasMcpError) as caught:
                    asyncio.run(run())
                self.assertEqual(caught.exception.code, code)


if __name__ == "__main__":
    unittest.main()

