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

    def test_list_assembly_history_calls_read_only_endpoint(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["query"] = str(request.url.query)
            seen["org"] = request.headers.get("x-org-id") or ""
            return httpx.Response(200, json={"ok": True, "items": [{"group_id": "group-1"}], "next_cursor": None, "history_available": True})

        async def run() -> dict:
            client = CajasClient(_settings(), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://cajas.example.test"))
            try:
                return await client.list_assembly_history(token="t", org_id="org-1", filters={"project": "Phoenix", "limit": 500})
            finally:
                await client.aclose()

        result = asyncio.run(run())
        self.assertEqual(seen["path"], "/api/assembly/history")
        self.assertEqual(seen["org"], "org-1")
        self.assertIn("project=Phoenix", seen["query"])
        self.assertIn("limit=100", seen["query"])
        self.assertTrue(result["history_available"])
        self.assertEqual(result["items"][0]["group_id"], "group-1")

    def test_smart_excel_preview_and_execute_paths(self) -> None:
        seen: list[tuple[str, str, dict]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode())
            seen.append((request.method, request.url.path, body))
            if request.url.path.endswith("/preview"):
                return httpx.Response(200, json={"ok": True, "summary": {"invalid_rows": 0}, "rows": []})
            return httpx.Response(200, json={"ok": True, "raw_entry_ids": ["raw-1"], "raw_group_ids": ["group-1"]})

        async def run() -> tuple[dict, dict]:
            client = CajasClient(_settings(), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://cajas.example.test"))
            try:
                payload = {"profile_id": "profile-1", "headers": ["date"], "rows": [], "column_mapping": {}, "voucher_rule": {}, "import_shape": "erp_line"}
                preview = await client.preview_raw_import(token="t", org_id="org", payload=payload)
                execute = await client.execute_raw_import(token="t", org_id="org", payload={**payload, "mode": "smart_merge"})
                return preview, execute
            finally:
                await client.aclose()

        preview, execute = asyncio.run(run())
        self.assertEqual(seen[0][0], "POST")
        self.assertEqual(seen[0][1], "/api/smart-excel/preview")
        self.assertEqual(seen[1][1], "/api/smart-excel/execute")
        self.assertEqual(preview["summary"]["invalid_rows"], 0)
        self.assertEqual(execute["raw_entry_ids"], ["raw-1"])

    def test_coa_preview_and_execute_paths(self) -> None:
        seen: list[tuple[str, str, dict]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode())
            seen.append((request.method, request.url.path, body))
            if request.url.path.endswith("/upload-preview"):
                return httpx.Response(200, json={"ok": True, "summary": {"add": 1}, "operations": []})
            return httpx.Response(200, json={"ok": True, "inserted": 1, "updated_rows": 0})

        async def run() -> tuple[dict, dict]:
            client = CajasClient(_settings(), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://cajas.example.test"))
            try:
                payload = {"headers": ["code", "name_ko", "name_en"], "rows": [{"code": "1000", "name_ko": "Cash"}]}
                preview = await client.preview_coa_import(token="t", org_id="org", profile_id="profile-1", payload=payload)
                execute = await client.execute_coa_import(token="t", org_id="org", profile_id="profile-1", payload=payload)
                return preview, execute
            finally:
                await client.aclose()

        preview, execute = asyncio.run(run())
        self.assertEqual(seen[0][1], "/api/coa/profiles/profile-1/upload-preview")
        self.assertEqual(seen[1][1], "/api/coa/profiles/profile-1/upload")
        self.assertEqual(preview["summary"]["add"], 1)
        self.assertEqual(execute["inserted"], 1)

    def test_standards_read_paths(self) -> None:
        seen: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.url.path, str(request.url.query)))
            if request.url.path == "/api/standards":
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "items": [
                            {"id": "std-1", "standard_type": "IFRS", "code": "IFRS 15.22-30", "level": "L1"},
                            {"id": "std-2", "standard_type": "IFRS", "code": "IFRS 9", "level": "L1"},
                        ],
                    },
                )
            if request.url.path == "/api/standards/std-1":
                return httpx.Response(200, json={"ok": True, "item": {"id": "std-1", "code": "IFRS 15.22-30"}})
            return httpx.Response(
                200,
                json={"ok": True, "items": [{"id": "tmpl-1", "group_id": "std-1", "level": "L2", "title": "Policy"}]},
            )

        async def run() -> tuple[dict, dict, dict]:
            client = CajasClient(_settings(), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://cajas.example.test"))
            try:
                standards = await client.list_standards(token="t", org_id="org", filters={"standard_type": "IFRS", "code": "IFRS 15", "level": "L1"})
                standard = await client.get_standard(token="t", org_id="org", standard_id="std-1")
                interpretations = await client.find_interpretations(token="t", org_id="org", group_id="std-1", query="policy", limit=20)
                return standards, standard, interpretations
            finally:
                await client.aclose()

        standards, standard, interpretations = asyncio.run(run())
        self.assertEqual(seen[0][0], "/api/standards")
        self.assertIn("standard_type=IFRS", seen[0][1])
        self.assertEqual(seen[1][0], "/api/standards/std-1")
        self.assertEqual(seen[2][0], "/api/standards/interpretations")
        self.assertEqual(standards["items"][0]["id"], "std-1")
        self.assertEqual(standard["item"]["id"], "std-1")
        self.assertEqual(interpretations["items"][0]["id"], "tmpl-1")


if __name__ == "__main__":
    unittest.main()
