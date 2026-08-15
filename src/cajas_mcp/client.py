from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx

from .config import Settings
from .errors import CajasMcpError, normalize_http_status


class CajasClient:
    def __init__(self, settings: Settings, *, http_client: httpx.AsyncClient | None = None) -> None:
        if not settings.cajas_api_base_url:
            raise CajasMcpError(
                "CAJAS_API_UNAVAILABLE",
                "CAJAS_API_BASE_URL is not configured.",
                requires_user_action=True,
            )
        self.settings = settings
        self._owned_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=settings.cajas_api_base_url,
            timeout=httpx.Timeout(settings.http_timeout),
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    def _headers(self, *, token: str, org_id: str | None = None, request_id: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {token}",
            "x-request-id": request_id or f"mcp_{uuid.uuid4().hex}",
        }
        if org_id:
            headers["x-org-id"] = org_id
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        org_id: str | None = None,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        retry_read: bool = True,
    ) -> dict[str, Any]:
        attempts = max(1, self.settings.http_retries + 1 if retry_read and method.upper() == "GET" else 1)
        last_error: CajasMcpError | None = None
        request_id = f"mcp_{uuid.uuid4().hex}"
        for attempt in range(attempts):
            try:
                response = await self._client.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers=self._headers(token=token, org_id=org_id, request_id=request_id),
                )
            except httpx.TimeoutException as exc:
                last_error = CajasMcpError("CAJAS_API_UNAVAILABLE", "CAJAS API request timed out.", retryable=True, details={"error": str(exc)})
            except httpx.HTTPError as exc:
                last_error = CajasMcpError("CAJAS_API_UNAVAILABLE", "CAJAS API request failed.", retryable=True, details={"error": str(exc)})
            else:
                if 200 <= response.status_code < 300:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise CajasMcpError("INTERNAL_ERROR", "CAJAS API returned non-JSON response.", details={"error": str(exc)})
                    if isinstance(payload, dict):
                        payload.setdefault("_request_id", request_id)
                        return payload
                    raise CajasMcpError("INTERNAL_ERROR", "CAJAS API returned unexpected JSON payload.")
                message = self._extract_error_message(response)
                details = self._extract_error_details(response)
                last_error = normalize_http_status(response.status_code, message, details)
            if attempt + 1 < attempts and last_error and last_error.retryable:
                await asyncio.sleep(0.15 * (attempt + 1))
                continue
            break
        raise last_error or CajasMcpError("INTERNAL_ERROR", "Unknown CAJAS API error.")

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:500] or f"CAJAS API returned HTTP {response.status_code}."
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str):
                return detail
            if isinstance(detail, dict):
                return str(detail.get("message") or detail.get("error") or detail)
            return str(payload.get("message") or payload.get("error") or payload)
        return str(payload)

    @staticmethod
    def _extract_error_details(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {"payload": payload}

    async def list_workspaces(self, *, token: str, include_archived: bool = False) -> dict[str, Any]:
        payload = await self._request("GET", "/api/orgs/memberships", token=token)
        memberships = payload.get("memberships") or payload.get("orgs") or []
        if not include_archived:
            memberships = [
                item
                for item in memberships
                if str(item.get("org_status") or item.get("status") or "active").lower() not in {"archived", "suspended"}
            ]
        return {"workspaces": memberships, "_request_id": payload.get("_request_id")}

    async def search_raw_entries(self, *, token: str, org_id: str, filters: dict[str, Any]) -> dict[str, Any]:
        params = {
            "status": filters.get("status"),
            "date_from": filters.get("date_from"),
            "date_to": filters.get("date_to"),
            "coa_profile_id": filters.get("coa_profile_id"),
            "limit": filters.get("limit", 50),
            "offset": self._cursor_to_offset(filters.get("cursor")),
        }
        params = {k: v for k, v in params.items() if v is not None}
        payload = await self._request("GET", "/api/raw-entries", token=token, org_id=org_id, params=params)
        items_payload = payload.get("items")
        if isinstance(items_payload, dict):
            items = items_payload.get("items") or []
            count_summary = items_payload.get("count_summary") or {}
        else:
            items = items_payload or []
            count_summary = {}
        items = self._client_side_filter_raw(items, filters)
        limit = int(filters.get("limit") or 50)
        offset = self._cursor_to_offset(filters.get("cursor"))
        total = int(count_summary.get("total") or 0)
        next_cursor = str(offset + limit) if total and offset + limit < total else None
        return {"raw_entries": items, "next_cursor": next_cursor, "_request_id": payload.get("_request_id")}

    async def get_raw_entry(self, *, token: str, org_id: str, raw_entry_id: str) -> dict[str, Any]:
        payload = await self._request("GET", f"/api/raw-entries/{raw_entry_id}", token=token, org_id=org_id)
        row = payload.get("raw_entry") or payload.get("item") or payload
        return {"raw_entry": row, "_request_id": payload.get("_request_id")}

    async def search_events(self, *, token: str, org_id: str, filters: dict[str, Any]) -> dict[str, Any]:
        params = {"state": filters.get("state"), "limit": filters.get("limit", 50)}
        params = {k: v for k, v in params.items() if v is not None}
        payload = await self._request("GET", "/api/events", token=token, org_id=org_id, params=params)
        items = payload.get("items") or []
        query = str(filters.get("query") or "").strip().lower()
        if query:
            items = [
                row
                for row in items
                if query in str(row.get("title") or row.get("description") or row.get("memo") or "").lower()
            ]
        return {"events": items, "next_cursor": None, "_request_id": payload.get("_request_id")}

    async def get_event(self, *, token: str, org_id: str, event_id: str) -> dict[str, Any]:
        payload = await self._request("GET", f"/api/events/{event_id}", token=token, org_id=org_id)
        return {"event": payload.get("event") or payload, "_request_id": payload.get("_request_id")}

    @staticmethod
    def _cursor_to_offset(cursor: Any) -> int:
        if cursor in (None, ""):
            return 0
        try:
            return max(0, int(str(cursor)))
        except ValueError:
            return 0

    @staticmethod
    def _client_side_filter_raw(items: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
        project = str(filters.get("project") or "").strip().lower()
        department = str(filters.get("department") or "").strip().lower()
        counterparty_id = str(filters.get("counterparty_id") or "").strip()
        query = str(filters.get("query") or "").strip().lower()
        result: list[dict[str, Any]] = []
        for row in items:
            if project and project not in str(row.get("project") or "").lower():
                continue
            if department and department not in str(row.get("department") or "").lower():
                continue
            row_counterparty = str(row.get("counterparty_id") or row.get("counterpart_id") or "").strip()
            if counterparty_id and row_counterparty != counterparty_id:
                continue
            if query:
                haystack = " ".join(
                    str(row.get(key) or "")
                    for key in ("description", "memo", "project", "department", "counterparty_name", "event_hint_key")
                ).lower()
                if query not in haystack:
                    continue
            result.append(row)
        return result

