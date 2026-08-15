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

QUERY_STOP_TERMS = {
    "same",
    "different",
    "workflow",
    "operational",
    "process",
    "responsibility",
    "related",
    "context",
    "general",
}

PRIVATE_IDENTIFIER_TERMS = {"cajas"}

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
    "\uac1c\ubc1c\ud658\uacbd": "development environment",
    "\uac1c\ubc1c": "development",
    "\ud658\uacbd": "environment",
    "\uc6b4\uc601": "operations",
    "\uc774\uc6a9\uad8c": "subscription",
    "\ubc30\ud3ec": "deployment",
    "\uc11c\ubc84": "server",
    "\ub370\uc774\ud130\ubca0\uc774\uc2a4": "database",
}

ENGLISH_CONCEPTS = {
    "development environment": "development environment",
    "cloud infrastructure": "cloud infrastructure",
    "cloud operations": "cloud operations",
    "saas subscription": "saas subscription",
    "saas": "saas",
    "aws": "aws",
    "ec2": "ec2",
    "nat gateway": "nat gateway",
    "azure": "azure",
    "gcp": "gcp",
    "postgresql": "postgresql",
    "docker": "docker",
    "kubernetes": "kubernetes",
    "deployment": "deployment",
    "database": "database",
    "server": "server",
    "api": "api",
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
    "development",
    "environment",
    "operations",
    "setup",
    "deployment",
    "server",
    "database",
    "postgresql",
    "docker",
    "kubernetes",
    "api",
}

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


@dataclass(frozen=True)
class CommunityValidationRequest:
    enabled: bool = False
    mode: CommunityMode = "BALANCED"


class CommunityValidationService:
    def __init__(
        self,
        provider: ExternalContextProvider,
        *,
        provider_enabled: bool,
        cache_ttl: int = 3600,
        max_queries: int = 4,
        max_search_requests: int = 4,
    ) -> None:
        self.provider = provider
        self.provider_enabled = provider_enabled
        self.cache_ttl = max(0, int(cache_ttl or 0))
        self.max_queries = max(1, min(int(max_queries or 4), 8))
        self.max_search_requests = max(1, min(int(max_search_requests or 4), 8))

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

        queries = _community_queries(concepts, request.mode, max_queries=self.max_queries)
        cache_key = _cache_key(getattr(self.provider, "site", "provider"), request.mode, [item["query"] for item in queries])
        cached = _cache_get(cache_key, self.cache_ttl)
        if cached is not None:
            return {**cached, "cache": {"hit": True, "key": cache_key}}

        evidence_by_key: dict[str, dict[str, Any]] = {}
        provider_metadata: dict[str, Any] = {}
        executed_initial: list[dict[str, str]] = []
        executed_fallback: list[dict[str, str]] = []
        requests_made = 0
        try:
            requests_made = await _run_queries(
                provider=self.provider,
                queries=queries,
                concepts=concepts,
                evidence_by_key=evidence_by_key,
                provider_metadata=provider_metadata,
                executed=executed_initial,
                request_budget=self.max_search_requests,
                requests_made=requests_made,
            )
            relevant_after_initial = [item for item in evidence_by_key.values() if item["classification"] != "IRRELEVANT"]
            if not relevant_after_initial and requests_made < self.max_search_requests:
                fallback_queries = _fallback_queries(concepts, request.mode, max_queries=self.max_queries)
                requests_made = await _run_queries(
                    provider=self.provider,
                    queries=fallback_queries,
                    concepts=concepts,
                    evidence_by_key=evidence_by_key,
                    provider_metadata=provider_metadata,
                    executed=executed_fallback,
                    request_budget=self.max_search_requests,
                    requests_made=requests_made,
                )
        except TimeoutError:
            return self._not_performed(request.mode, "COMMUNITY_PROVIDER_TIMEOUT")
        except Exception as exc:
            return self._not_performed(request.mode, f"COMMUNITY_PROVIDER_{type(exc).__name__.upper()}")

        evidence = list(evidence_by_key.values())
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
            "queries": [*executed_initial, *executed_fallback],
            "query_strategy": {
                "initial_queries": executed_initial,
                "fallback_queries": executed_fallback,
                "fallback_used": bool(executed_fallback),
                "requests_made": requests_made,
                "max_search_requests": self.max_search_requests,
            },
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
            if phrase not in concepts:
                concepts.append(phrase)
    source_lower = source.lower()
    for key, phrase in ENGLISH_CONCEPTS.items():
        if key in source_lower and phrase not in concepts:
            concepts.append(phrase)

    sanitized = sanitize_external_query(source, max_terms=14)
    for token in sanitized.split():
        clean = _clean_concept(token)
        if clean and _is_allowed_query_concept(clean) and clean not in concepts:
            concepts.append(clean)
    return concepts[:12]


def _community_queries(concepts: list[str], mode: str, *, max_queries: int = 4) -> list[dict[str, str]]:
    concrete = _ranked_query_concepts(concepts)
    candidates: list[list[str]] = []
    if len(concrete) >= 3:
        candidates.append(concrete[:3])
    if len(concrete) >= 4:
        candidates.append([concrete[0], concrete[2], concrete[3]])
    if len(concrete) >= 5:
        candidates.append([concrete[1], concrete[3], concrete[4]])
    return _query_records(candidates, mode, "INITIAL_NEUTRAL", max_queries)


def _fallback_queries(concepts: list[str], mode: str, *, max_queries: int = 4) -> list[dict[str, str]]:
    concrete = _ranked_query_concepts(concepts)
    pairs: list[list[str]] = []
    for first, second in (
        ("cloud infrastructure", "saas"),
        ("development environment", "cloud infrastructure"),
        ("saas", "subscription"),
        ("aws", "ec2"),
        ("nat", "gateway"),
    ):
        if first in concrete and second in concrete:
            pairs.append([first, second])
    for index in range(0, max(0, len(concrete) - 1)):
        pairs.append(concrete[index : index + 2])
    return _query_records(pairs, mode, "FALLBACK_DECOMPOSED", max_queries)


def _query_records(groups: list[list[str]], mode: str, purpose: str, max_queries: int) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in groups:
        terms = [term for term in group if _is_allowed_query_concept(term)]
        if len(terms) < 2:
            continue
        query = " ".join(terms)
        key = " ".join(sorted(terms))
        if key in seen:
            continue
        seen.add(key)
        records.append({"purpose": purpose, "mode": mode, "query": query})
        if len(records) >= max_queries:
            break
    return records


def _ranked_query_concepts(concepts: list[str]) -> list[str]:
    priority = [
        "cloud infrastructure",
        "cloud operations",
        "development environment",
        "saas subscription",
        "nat gateway",
        "saas",
        "subscription",
        "implementation",
        "operations",
        "deployment",
        "aws",
        "ec2",
        "nat",
        "gateway",
        "docker",
        "postgresql",
        "database",
        "api",
        "migration",
        "maintenance",
        "server",
        "software",
    ]
    normalized = []
    for concept in concepts:
        clean = _clean_phrase(concept)
        if clean and _is_allowed_query_concept(clean) and clean not in normalized:
            normalized.append(clean)
    ranked = [item for item in priority if item in normalized]
    ranked.extend(item for item in normalized if item not in ranked)
    return ranked[:12]


def _classify_results(results: list[ExternalSearchResult], purpose: str, concepts: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    concept_set = {c.lower() for c in concepts}
    for result in results:
        text = " ".join([result.title or "", result.summary or "", " ".join(result.tags or [])]).lower()
        overlap = sorted(token for token in concept_set if token and token in text)
        support_hits = sum(1 for token in SUPPORT_TERMS - QUERY_STOP_TERMS if token in text)
        challenge_hits = sum(1 for token in CHALLENGE_TERMS if token in text)
        if len(overlap) < 1 and support_hits + challenge_hits < 2:
            classification = "IRRELEVANT"
            reason = "Insufficient overlap with sanitized operational concepts."
        elif challenge_hits >= 2 and challenge_hits >= support_hits:
            classification = "CONTRADICTING"
            reason = "Public discussion appears to describe separate lifecycle or responsibility terms."
        elif support_hits >= 2 and support_hits > challenge_hits:
            classification = "SUPPORTING"
            reason = "Public discussion appears to describe related operational workflow terms."
        else:
            classification = "NEUTRAL" if overlap else "IRRELEVANT"
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


async def _run_queries(
    *,
    provider: ExternalContextProvider,
    queries: list[dict[str, str]],
    concepts: list[str],
    evidence_by_key: dict[str, dict[str, Any]],
    provider_metadata: dict[str, Any],
    executed: list[dict[str, str]],
    request_budget: int,
    requests_made: int,
) -> int:
    for query in queries:
        if requests_made >= request_budget:
            break
        results = await provider.search(query["query"], limit=5)
        requests_made += 1
        metadata = getattr(provider, "last_metadata", {}) or {}
        if metadata:
            provider_metadata.update(metadata)
        executed.append(query)
        for item in _classify_results(results, query["purpose"], concepts):
            key = _evidence_key(item)
            if key not in evidence_by_key:
                evidence_by_key[key] = item
        if any(item["classification"] != "IRRELEVANT" for item in evidence_by_key.values()):
            break
    return requests_made


def _evidence_key(item: dict[str, Any]) -> str:
    if item.get("question_id") is not None:
        return f"question:{item['question_id']}"
    return f"url:{item.get('url') or item.get('title')}"


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


def _clean_phrase(value: str) -> str:
    terms = [_clean_concept(part) for part in str(value or "").split()]
    terms = [term for term in terms if term]
    return " ".join(terms)


def _is_allowed_query_concept(value: str) -> bool:
    clean = _clean_phrase(value)
    if not clean or clean in PRIVATE_IDENTIFIER_TERMS:
        return False
    if clean in QUERY_STOP_TERMS:
        return False
    if clean in CONCEPT_ALLOWLIST:
        return True
    return all(part in CONCEPT_ALLOWLIST and part not in QUERY_STOP_TERMS for part in clean.split())


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
