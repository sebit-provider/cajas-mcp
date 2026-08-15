from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

from .adapters.external_context import ExternalContextProvider, ExternalSearchResult, TRUST_UNTRUSTED_EXTERNAL_DATA
from .schemas.raw import RawEntry
from .security.sanitizer import sanitize_external_query

CommunityMode = Literal["SUPPORT", "CHALLENGE", "BALANCED"]

SUPPORT_TERMS = {
    "workflow",
    "process",
    "lifecycle",
    "together",
    "same",
    "integration",
    "implementation",
    "migration",
    "subscription",
    "license",
    "billing",
    "receivable",
    "deliverable",
    "professional",
    "services",
    "consulting",
    "maintenance",
    "support",
    "cloud",
    "infrastructure",
}

CHALLENGE_TERMS = {
    "separate",
    "different",
    "split",
    "independent",
    "responsibility",
    "recognition",
    "delivery",
    "operations",
}

KOREAN_CONCEPTS = {
    "\ub9e4\ucd9c\ucc44\uad8c": "accounts receivable",
    "\ucc44\uad8c": "accounts receivable",
    "\ud68c\uc218": "collection",
    "\uc785\uae08": "payment collection",
    "\ub9e4\ucd9c": "billing revenue",
    "\ub77c\uc774\uc120\uc2a4": "subscription license",
    "\uad6c\ub3c5": "subscription",
    "\ucee8\uc124\ud305": "consulting professional services",
    "\uc0b0\ucd9c\ubb3c": "deliverable",
    "\uac80\uc218": "deliverable acceptance",
    "\uc6a9\uc5ed": "professional services",
    "\uc678\uc8fc": "outsourced services",
    "\uad6c\ucd95": "implementation",
    "\ub9c8\uc774\uadf8\ub808\uc774\uc158": "migration",
    "\uad50\uc721": "training",
    "\uc720\uc9c0\ubcf4\uc218": "maintenance support",
    "\uac10\uc0ac": "audit support",
    "\ud074\ub77c\uc6b0\ub4dc": "cloud infrastructure",
}

CONCEPT_ALLOWLIST = {
    *SUPPORT_TERMS,
    *CHALLENGE_TERMS,
    "accounts",
    "collection",
    "payment",
    "revenue",
    "audit",
    "training",
    "outsourced",
    "acceptance",
    "saas",
    "aws",
    "azure",
    "gcp",
    "ec2",
    "gateway",
    "nat",
    "erp",
    "software",
    "project",
}

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


@dataclass(frozen=True)
class CommunityValidationRequest:
    enabled: bool = False
    mode: CommunityMode = "BALANCED"


class CommunityValidationService:
    def __init__(self, provider: ExternalContextProvider, *, provider_enabled: bool, cache_ttl: int = 3600) -> None:
        self.provider = provider
        self.provider_enabled = provider_enabled
        self.cache_ttl = max(0, int(cache_ttl or 0))

    async def validate(
        self,
        *,
        request: CommunityValidationRequest,
        raw_entries: list[RawEntry],
        recommendations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not request.enabled:
            return {
                "requested": False,
                "performed": False,
                "assessment": "NOT_PERFORMED",
                "reason": "USER_NOT_REQUESTED",
                "score_effect": "NONE",
                "mutation": False,
            }
        if not self.provider_enabled:
            return self._not_performed(request.mode, "PROVIDER_DISABLED")

        concepts = _community_query_concepts(raw_entries)
        if not concepts:
            return self._not_performed(request.mode, "NO_SANITIZED_QUERY_TERMS")

        queries = _community_queries(concepts, request.mode)
        cache_key = _cache_key(getattr(self.provider, "site", "provider"), request.mode, [item["query"] for item in queries])
        cached = _cache_get(cache_key, self.cache_ttl)
        if cached is not None:
            return {**cached, "cache": {"hit": True, "key": cache_key}}

        evidence: list[dict[str, Any]] = []
        provider_metadata: dict[str, Any] = {}
        try:
            for query in queries:
                results = await self.provider.search(query["query"], limit=5)
                provider_metadata = getattr(self.provider, "last_metadata", {}) or provider_metadata
                evidence.extend(_classify_results(results, query["purpose"], concepts))
        except TimeoutError:
            return self._not_performed(request.mode, "COMMUNITY_PROVIDER_TIMEOUT")
        except Exception as exc:
            return self._not_performed(request.mode, f"COMMUNITY_PROVIDER_{type(exc).__name__.upper()}")

        relevant = [item for item in evidence if item["classification"] != "IRRELEVANT"]
        supporting = [item for item in relevant if item["classification"] == "SUPPORTING"]
        contradicting = [item for item in relevant if item["classification"] == "CONTRADICTING"]
        neutral = [item for item in relevant if item["classification"] == "NEUTRAL"]
        assessment = _assessment(len(supporting), len(contradicting), len(neutral))

        output = {
            "requested": True,
            "performed": True,
            "provider": "STACK_EXCHANGE",
            "mode": request.mode,
            "trust": TRUST_UNTRUSTED_EXTERNAL_DATA,
            "queries": queries,
            "sources_checked": len(evidence),
            "relevant_sources": len(relevant),
            "supporting_patterns": len(supporting),
            "contradicting_patterns": len(contradicting),
            "neutral_patterns": len(neutral),
            "assessment": assessment,
            "community_evidence_confidence": _community_confidence(len(relevant), len(supporting), len(contradicting)),
            "evidence": relevant[:8],
            "summary": _summary(assessment, len(supporting), len(contradicting), len(neutral)),
            "provider_metadata": _safe_provider_metadata(provider_metadata),
            "cache": {"hit": False, "key": cache_key},
            "score_effect": "NONE",
            "mutation": False,
        }
        _cache_put(cache_key, output, self.cache_ttl)
        return output

    @staticmethod
    def _not_performed(mode: str, reason: str) -> dict[str, Any]:
        return {
            "requested": True,
            "performed": False,
            "provider": "STACK_EXCHANGE",
            "mode": mode,
            "trust": TRUST_UNTRUSTED_EXTERNAL_DATA,
            "assessment": "NOT_PERFORMED",
            "reason": reason,
            "score_effect": "NONE",
            "mutation": False,
        }


def parse_community_validation(value: Any = None, *, enabled: bool = False, mode: str | None = None) -> CommunityValidationRequest:
    if isinstance(value, dict):
        enabled = bool(value.get("enabled", enabled))
        mode = str(value.get("mode") or mode or "BALANCED")
    parsed_mode = str(mode or "BALANCED").strip().upper()
    if parsed_mode not in {"SUPPORT", "CHALLENGE", "BALANCED"}:
        parsed_mode = "BALANCED"
    return CommunityValidationRequest(enabled=enabled, mode=parsed_mode)  # type: ignore[arg-type]


def _community_query_concepts(entries: list[RawEntry]) -> list[str]:
    source = " ".join(
        " ".join(
            [
                entry.description or "",
                entry.memo or "",
                entry.event_hint_key or "",
                " ".join(str(code) for code in entry.account_codes),
            ]
        )
        for entry in entries
    )
    concepts: list[str] = []
    for key, phrase in KOREAN_CONCEPTS.items():
        if key in source:
            for token in phrase.split():
                if token not in concepts:
                    concepts.append(token)

    sanitized = sanitize_external_query(source, max_terms=14)
    for token in sanitized.split():
        clean = _clean_concept(token)
        if clean and clean in CONCEPT_ALLOWLIST and clean not in concepts:
            concepts.append(clean)
    return concepts[:12]


def _community_queries(concepts: list[str], mode: str) -> list[dict[str, str]]:
    base = " ".join(concepts[:8])
    queries: list[dict[str, str]] = []
    if mode in {"SUPPORT", "BALANCED"}:
        queries.append({"purpose": "SUPPORT", "query": f"{base} same workflow operational process"})
    if mode in {"CHALLENGE", "BALANCED"}:
        queries.append({"purpose": "CHALLENGE", "query": f"{base} separate lifecycle responsibility process"})
    return queries


def _classify_results(results: list[ExternalSearchResult], purpose: str, concepts: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    concept_set = {c.lower() for c in concepts}
    for result in results:
        text = " ".join([result.title or "", result.summary or "", " ".join(result.tags or [])]).lower()
        overlap = sorted(token for token in concept_set if token and token in text)
        support_hits = sum(1 for token in SUPPORT_TERMS if token in text)
        challenge_hits = sum(1 for token in CHALLENGE_TERMS if token in text)
        if len(overlap) < 1 and support_hits + challenge_hits < 2:
            classification = "IRRELEVANT"
            reason = "Insufficient overlap with sanitized operational concepts."
        elif purpose == "CHALLENGE" and challenge_hits > 0 and support_hits <= challenge_hits + 2:
            classification = "CONTRADICTING"
            reason = "Public discussion appears to describe separate lifecycle or responsibility terms."
        elif purpose == "SUPPORT" and support_hits > 0 and challenge_hits <= support_hits + 2:
            classification = "SUPPORTING"
            reason = "Public discussion appears to describe related operational workflow terms."
        elif support_hits > challenge_hits:
            classification = "SUPPORTING"
            reason = "Public discussion appears to describe related operational workflow terms."
        elif challenge_hits > support_hits:
            classification = "CONTRADICTING"
            reason = "Public discussion appears to describe separate lifecycle or responsibility terms."
        else:
            classification = _tie_break_classification(purpose, bool(overlap))
            reason = "Public discussion overlaps with the validation query but does not resolve direction strongly."
        out.append(
            {
                "classification": classification,
                "purpose": purpose,
                "site": result.provider,
                "question_id": result.question_id,
                "title": _truncate(result.title, 180),
                "url": result.url,
                "tags": result.tags or [],
                "question_score": result.question_score if result.question_score is not None else result.score,
                "accepted_answer": result.accepted_answer,
                "answer_score": result.answer_score,
                "matched_concepts": overlap[:8],
                "reason": reason,
                "trust": TRUST_UNTRUSTED_EXTERNAL_DATA,
            }
        )
    return out


def _tie_break_classification(purpose: str, has_overlap: bool) -> str:
    if purpose == "SUPPORT" and has_overlap:
        return "SUPPORTING"
    if purpose == "CHALLENGE" and has_overlap:
        return "CONTRADICTING"
    return "NEUTRAL"


def _assessment(supporting: int, contradicting: int, neutral: int) -> str:
    if supporting == 0 and contradicting == 0 and neutral == 0:
        return "INSUFFICIENT_EVIDENCE"
    if supporting > 0 and contradicting > 0:
        return "MIXED"
    if supporting > 0:
        return "SUPPORTS"
    if contradicting > 0:
        return "CHALLENGES"
    return "INSUFFICIENT_EVIDENCE"


def _community_confidence(relevant: int, supporting: int, contradicting: int) -> float:
    if relevant <= 0:
        return 0.0
    balance_penalty = 0.2 if supporting and contradicting else 0.0
    return round(max(0.0, min(0.75, 0.18 + min(relevant, 6) * 0.08 - balance_penalty)), 4)


def _summary(assessment: str, supporting: int, contradicting: int, neutral: int) -> str:
    if assessment == "INSUFFICIENT_EVIDENCE":
        return "No sufficiently relevant public community evidence was found."
    return (
        f"Community validation is {assessment.lower()}: "
        f"{supporting} supporting, {contradicting} contradicting, and {neutral} neutral public discussion(s). "
        "This is operational context only, not accounting authority."
    )


def _safe_provider_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: metadata.get(key)
        for key in ("http_status", "quota_remaining", "quota_max", "backoff", "has_more")
        if key in metadata
    }


def _clean_concept(value: str) -> str:
    return re.sub(r"[^a-z0-9+-]", "", str(value or "").lower())


def _truncate(value: str, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def _cache_key(site: str, mode: str, queries: list[str]) -> str:
    material = "|".join([site, mode, *queries]).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:24]


def _cache_get(key: str, ttl: int) -> dict[str, Any] | None:
    if ttl <= 0:
        return None
    row = _CACHE.get(key)
    if not row:
        return None
    expires_at, value = row
    if expires_at <= time.time():
        _CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: dict[str, Any], ttl: int) -> None:
    if ttl <= 0:
        return
    if len(_CACHE) > 256:
        for old_key in list(_CACHE)[:64]:
            _CACHE.pop(old_key, None)
    _CACHE[key] = (time.time() + ttl, value)
