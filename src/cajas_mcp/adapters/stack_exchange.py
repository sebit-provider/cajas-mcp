from __future__ import annotations

from datetime import UTC, datetime
from html import unescape
from typing import Any

import httpx

from .external_context import ExternalSearchResult


class StackExchangeProvider:
    def __init__(
        self,
        *,
        site: str = "stackoverflow",
        key: str | None = None,
        timeout: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.site = site
        self.key = key
        self.timeout = timeout
        self._owned_client = http_client is None
        self._client = http_client or httpx.AsyncClient(base_url="https://api.stackexchange.com/2.3", timeout=timeout)
        self.last_metadata: dict[str, Any] = {}

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def search(self, query: str, *, limit: int = 5) -> list[ExternalSearchResult]:
        params: dict[str, Any] = {
            "order": "desc",
            "sort": "relevance",
            "q": query,
            "site": self.site,
            "pagesize": max(1, min(limit, 10)),
            "filter": "default",
        }
        if self.key:
            params["key"] = self.key
        response = await self._client.get("/search/advanced", params=params)
        if response.status_code == 429:
            self.last_metadata = {"http_status": 429}
            return []
        response.raise_for_status()
        payload = response.json()
        self.last_metadata = {
            "http_status": response.status_code,
            "quota_remaining": payload.get("quota_remaining"),
            "quota_max": payload.get("quota_max"),
            "backoff": payload.get("backoff"),
            "has_more": payload.get("has_more"),
        }
        retrieved_at = datetime.now(UTC).isoformat()
        results: list[ExternalSearchResult] = []
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            results.append(
                ExternalSearchResult(
                    provider="stack_exchange",
                    title=unescape(str(item.get("title") or "")),
                    url=str(item.get("link") or ""),
                    summary=" ".join(str(tag) for tag in item.get("tags") or []),
                    question_id=item.get("question_id") if isinstance(item.get("question_id"), int) else None,
                    score=item.get("score") if isinstance(item.get("score"), int) else None,
                    question_score=item.get("score") if isinstance(item.get("score"), int) else None,
                    tags=[str(tag) for tag in item.get("tags") or []],
                    accepted_answer=bool(item.get("accepted_answer_id") or item.get("is_answered"))
                    if item.get("is_answered") is not None or item.get("accepted_answer_id") is not None
                    else None,
                    retrieved_at=retrieved_at,
                )
            )
        return results

    async def extract_work_patterns(self, results: list[ExternalSearchResult]) -> list[str]:
        patterns: list[str] = []
        for result in results:
            terms = ", ".join(result.tags or [])
            if terms:
                patterns.append(f"Community discussions associate these operational terms: {terms}.")
        return patterns[:5]
