from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


TRUST_UNTRUSTED_EXTERNAL_DATA = "UNTRUSTED_EXTERNAL_DATA"


@dataclass(frozen=True)
class ExternalSearchResult:
    provider: str
    title: str
    url: str
    summary: str
    question_id: int | None = None
    score: int | None = None
    question_score: int | None = None
    answer_score: int | None = None
    tags: list[str] | None = None
    accepted_answer: bool | None = None
    retrieved_at: str | None = None
    content_summary: str | None = None
    content_reviewed: bool = False
    retrieval_relevance: str | None = None
    validation_relevance: str | None = None
    content_license: str | None = None
    trust: str = TRUST_UNTRUSTED_EXTERNAL_DATA


class ExternalContextProvider(Protocol):
    async def search(self, query: str, *, limit: int = 5) -> list[ExternalSearchResult]:
        ...

    async def extract_work_patterns(self, results: list[ExternalSearchResult]) -> list[str]:
        ...


class DisabledExternalContextProvider:
    async def search(self, query: str, *, limit: int = 5) -> list[ExternalSearchResult]:
        return []

    async def extract_work_patterns(self, results: list[ExternalSearchResult]) -> list[str]:
        return []
