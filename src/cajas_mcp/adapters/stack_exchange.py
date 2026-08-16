from __future__ import annotations

from datetime import UTC, datetime
from html import unescape
import re
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
        max_evidence_items: int = 4,
        max_answers_per_question: int = 2,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.site = site
        self.key = key
        self.timeout = timeout
        self.max_evidence_items = max(1, min(int(max_evidence_items or 4), 8))
        self.max_answers_per_question = max(0, min(int(max_answers_per_question or 2), 5))
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
        response = await self._client.get("/search/excerpts", params=params)
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
            summary = unescape(str(item.get("excerpt") or item.get("body") or " ".join(str(tag) for tag in item.get("tags") or [])))
            results.append(
                ExternalSearchResult(
                    provider="stack_exchange",
                    title=unescape(str(item.get("title") or "")),
                    url=str(item.get("link") or ""),
                    summary=summary,
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
        return await self._enrich_results(results)

    async def extract_work_patterns(self, results: list[ExternalSearchResult]) -> list[str]:
        patterns: list[str] = []
        for result in results:
            terms = ", ".join(result.tags or [])
            if terms:
                patterns.append(f"Community discussions associate these operational terms: {terms}.")
        return patterns[:5]

    async def _enrich_results(self, results: list[ExternalSearchResult]) -> list[ExternalSearchResult]:
        question_ids = [result.question_id for result in results if result.question_id is not None]
        if not question_ids:
            return results
        question_ids = list(dict.fromkeys(question_ids))[: self.max_evidence_items]
        details = await self._fetch_question_details(question_ids)
        answers = await self._fetch_answers(question_ids) if self.max_answers_per_question > 0 else {}
        enriched: list[ExternalSearchResult] = []
        for result in results:
            if result.question_id not in question_ids:
                enriched.append(result)
                continue
            detail = details.get(result.question_id or -1, {})
            answer_rows = answers.get(result.question_id or -1, [])
            body_summary = _summarize_external_text(str(detail.get("body") or ""))
            answer_summary = _summarize_external_text(" ".join(str(row.get("body") or "") for row in answer_rows))
            content_parts = [part for part in (body_summary, answer_summary) if part]
            enriched.append(
                ExternalSearchResult(
                    provider=result.provider,
                    title=result.title or unescape(str(detail.get("title") or "")),
                    url=result.url or str(detail.get("link") or ""),
                    summary=result.summary,
                    question_id=result.question_id,
                    score=result.score,
                    question_score=result.question_score if result.question_score is not None else detail.get("score"),
                    answer_score=max((int(row.get("score") or 0) for row in answer_rows), default=None) if answer_rows else result.answer_score,
                    tags=result.tags or [str(tag) for tag in detail.get("tags") or []],
                    accepted_answer=(
                        result.accepted_answer
                        if result.accepted_answer is not None
                        else bool(detail.get("accepted_answer_id") or any(row.get("is_accepted") for row in answer_rows))
                    ),
                    retrieved_at=result.retrieved_at,
                    content_summary=" ".join(content_parts),
                    content_reviewed=bool(content_parts),
                    retrieval_relevance="SEARCH_MATCH",
                    validation_relevance=None,
                    content_license=str(detail.get("content_license") or "") or None,
                )
            )
        return enriched

    async def _fetch_question_details(self, question_ids: list[int]) -> dict[int, dict[str, Any]]:
        params = self._common_params(
            {
                "order": "desc",
                "sort": "activity",
                "site": self.site,
                "filter": "withbody",
            }
        )
        response = await self._client.get(f"/questions/{';'.join(str(item) for item in question_ids)}", params=params)
        if response.status_code == 429:
            self.last_metadata = {**self.last_metadata, "detail_http_status": 429}
            return {}
        response.raise_for_status()
        payload = response.json()
        self._merge_metadata(payload, "detail")
        return {int(item["question_id"]): item for item in payload.get("items") or [] if isinstance(item, dict) and isinstance(item.get("question_id"), int)}

    async def _fetch_answers(self, question_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        params = self._common_params(
            {
                "order": "desc",
                "sort": "votes",
                "site": self.site,
                "pagesize": max(1, min(self.max_answers_per_question * len(question_ids), 20)),
                "filter": "withbody",
            }
        )
        response = await self._client.get(f"/questions/{';'.join(str(item) for item in question_ids)}/answers", params=params)
        if response.status_code == 429:
            self.last_metadata = {**self.last_metadata, "answers_http_status": 429}
            return {}
        response.raise_for_status()
        payload = response.json()
        self._merge_metadata(payload, "answers")
        grouped: dict[int, list[dict[str, Any]]] = {}
        for item in payload.get("items") or []:
            if not isinstance(item, dict) or not isinstance(item.get("question_id"), int):
                continue
            rows = grouped.setdefault(int(item["question_id"]), [])
            if len(rows) < self.max_answers_per_question:
                rows.append(item)
        return grouped

    def _common_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.key:
            params["key"] = self.key
        return params

    def _merge_metadata(self, payload: dict[str, Any], prefix: str) -> None:
        self.last_metadata.update(
            {
                f"{prefix}_quota_remaining": payload.get("quota_remaining"),
                f"{prefix}_quota_max": payload.get("quota_max"),
                f"{prefix}_backoff": payload.get("backoff"),
                f"{prefix}_has_more": payload.get("has_more"),
            }
        )


def _summarize_external_text(value: str, *, max_chars: int = 700) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars].rstrip()
