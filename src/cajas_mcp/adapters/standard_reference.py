from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from cajas_mcp.security.sanitizer import sanitize_external_query


LEVEL_MEANINGS = {
    "L1": "EXTERNAL_STANDARD",
    "L2": "INTERNAL_POLICY",
    "L3": "TEMPORARY_OR_SUBJECTIVE",
}


OFFICIAL_STANDARD_URLS = {
    "IFRS 15": "https://www.ifrs.org/issued-standards/list-of-standards/ifrs-15-revenue-from-contracts-with-customers/",
    "IAS 36": "https://www.ifrs.org/issued-standards/list-of-standards/ias-36-impairment-of-assets/",
}


TOPIC_LOCATORS = [
    {
        "framework": "IFRS",
        "reference_code": "IFRS 15.22-30",
        "standard_key": "IFRS 15",
        "keywords": {"performance", "obligation", "distinct", "bundle", "contract", "revenue", "implementation", "migration", "saas"},
        "suggested_cajas_name": "\uacc4\uc57d \ub0b4 \uc218\ud589 \uc758\ubb34 \uc2dd\ubcc4",
        "suggested_cajas_description": "\uacc4\uc57d\uc5d0 \ud3ec\ud568\ub41c \uc7ac\ud654 \ub610\ub294 \uc11c\ube44\uc2a4\uc758 \uad6c\ubd84 \ud310\ub2e8\uc5d0 \ucc38\uace0\ud558\ub294 \uc678\ubd80 \uae30\uc900 \ubc94\uc704.",
    },
    {
        "framework": "IFRS",
        "reference_code": "IAS 36.9-14",
        "standard_key": "IAS 36",
        "keywords": {"impairment", "recoverable", "asset", "indicator", "cash", "generating", "cgu", "goodwill"},
        "suggested_cajas_name": "\uc190\uc0c1 \uc9d5\ud6c4 \ubc0f \ud68c\uc218\uac00\ub2a5\uc561 \uac80\ud1a0",
        "suggested_cajas_description": "\uc790\uc0b0 \uc190\uc0c1 \uc9d5\ud6c4\uc640 \ud68c\uc218\uac00\ub2a5\uc561 \uac80\ud1a0 \ud544\uc694\uc131\uc744 \ud310\ub2e8\ud560 \ub54c \ucc38\uace0\ud558\ub294 \uc678\ubd80 \uae30\uc900 \ubc94\uc704.",
    },
]


@dataclass(frozen=True)
class StandardLocator:
    framework: str
    standard: str
    paragraph_from: str | None
    paragraph_to: str | None
    normalized: str


class StandardReferenceProvider(Protocol):
    async def resolve(self, *, framework: str, query: str, event_context: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


class DeterministicIFRSReferenceProvider:
    async def resolve(self, *, framework: str, query: str, event_context: dict[str, Any] | None = None) -> dict[str, Any]:
        fw = str(framework or "IFRS").strip().upper()
        if fw not in {"IFRS", "IAS"}:
            return _not_found("UNSUPPORTED_FRAMEWORK")
        raw_query = _combined_query(query=query, event_context=event_context)
        clean_query = sanitize_standard_query(raw_query)
        explicit = extract_standard_locators(raw_query)
        candidates: list[dict[str, Any]] = []
        for locator in explicit:
            candidates.append(_candidate_from_locator(locator, confidence=0.86, reason="EXPLICIT_LOCATOR"))
        tokens = set(re.findall(r"[a-z0-9]+", clean_query.lower()))
        for topic in TOPIC_LOCATORS:
            if fw == "IAS" and not str(topic["reference_code"]).startswith("IAS "):
                continue
            overlap = tokens & set(topic["keywords"])
            if len(overlap) < 2:
                continue
            locator = parse_standard_locator(str(topic["reference_code"]))
            if not locator:
                continue
            candidate = _candidate_from_locator(locator, confidence=min(0.82, 0.45 + len(overlap) * 0.08), reason="TOPIC_KEYWORD_MATCH")
            candidate["matched_terms"] = sorted(overlap)
            candidate["suggested_cajas_name"] = topic["suggested_cajas_name"]
            candidate["suggested_cajas_description"] = topic["suggested_cajas_description"]
            candidates.append(candidate)
        deduped = _dedupe_candidates(candidates)
        if not deduped:
            return {
                "available": True,
                "resolved": False,
                "reason": "STANDARD_REFERENCE_NOT_FOUND",
                "requires_manual_reference": True,
                "sanitized_query": clean_query,
                "candidates": [],
            }
        deduped.sort(key=lambda item: float(item.get("confidence") or 0), reverse=True)
        ambiguous = len(deduped) > 1 and float(deduped[0].get("confidence") or 0) - float(deduped[1].get("confidence") or 0) < 0.1
        return {
            "available": True,
            "resolved": True,
            "ambiguous": ambiguous,
            "requires_review": True,
            "sanitized_query": clean_query,
            "candidates": deduped[:5],
        }


def sanitize_standard_query(text: str) -> str:
    clean = sanitize_external_query(text)
    clean = re.sub(r"\b[A-Z]{2,}-?\d{3,}\b", " ", clean)
    clean = re.sub(r"\b\d{4,}[-/]\d{2,}\b", " ", clean)
    clean = re.sub(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()[:300]


def _combined_query(*, query: str, event_context: dict[str, Any] | None) -> str:
    parts = [str(query or "")]
    if isinstance(event_context, dict):
        for key in ("title", "summary", "topic", "judgment_question"):
            value = str(event_context.get(key) or "").strip()
            if value:
                parts.append(value)
    return " ".join(parts)


def parse_standard_locator(text: str) -> StandardLocator | None:
    match = re.search(r"\b(IFRS|IAS)\s*([0-9]{1,2})(?:\s*[.\u00b6]?\s*([0-9A-Za-z]+)(?:\s*[-\u2013]\s*([0-9A-Za-z]+))?)?", text, re.IGNORECASE)
    if not match:
        return None
    family = match.group(1).upper()
    standard_num = match.group(2)
    para_from = match.group(3)
    para_to = match.group(4)
    standard = f"{family} {standard_num}"
    normalized = standard
    if para_from:
        normalized += f".{para_from}"
        if para_to and para_to != para_from:
            normalized += f"-{para_to}"
    return StandardLocator(
        framework=family,
        standard=standard,
        paragraph_from=para_from,
        paragraph_to=para_to,
        normalized=normalized,
    )


def extract_standard_locators(text: str) -> list[StandardLocator]:
    locators: list[StandardLocator] = []
    for match in re.finditer(r"\b(?:IFRS|IAS)\s*[0-9]{1,2}(?:\s*[.\u00b6]?\s*[0-9A-Za-z]+(?:\s*[-\u2013]\s*[0-9A-Za-z]+)?)?", text, re.IGNORECASE):
        locator = parse_standard_locator(match.group(0))
        if locator:
            locators.append(locator)
    return locators


def normalize_reference_code(code: str) -> str:
    locator = parse_standard_locator(code)
    if locator:
        return locator.normalized.upper()
    return re.sub(r"\s+", " ", str(code or "").strip().upper())


def locator_includes(existing_code: str, incoming_code: str) -> bool:
    existing = parse_standard_locator(existing_code)
    incoming = parse_standard_locator(incoming_code)
    if not existing or not incoming or existing.standard != incoming.standard:
        return False
    if not existing.paragraph_from or not incoming.paragraph_from:
        return normalize_reference_code(existing_code) == normalize_reference_code(incoming_code)
    try:
        ex_from = int(re.sub(r"\D", "", existing.paragraph_from))
        ex_to = int(re.sub(r"\D", "", existing.paragraph_to or existing.paragraph_from))
        in_from = int(re.sub(r"\D", "", incoming.paragraph_from))
        in_to = int(re.sub(r"\D", "", incoming.paragraph_to or incoming.paragraph_from))
    except ValueError:
        return normalize_reference_code(existing_code) == normalize_reference_code(incoming_code)
    return ex_from <= in_from and in_to <= ex_to


def level_payload(code: str) -> dict[str, str]:
    level = str(code or "").upper()
    return {"code": level, "meaning": LEVEL_MEANINGS.get(level, "UNKNOWN")}


def _candidate_from_locator(locator: StandardLocator, *, confidence: float, reason: str) -> dict[str, Any]:
    source_url = OFFICIAL_STANDARD_URLS.get(locator.standard)
    return {
        "framework": "IFRS" if locator.framework in {"IFRS", "IAS"} else locator.framework,
        "reference_code": locator.normalized,
        "normalized": {
            "framework": locator.framework,
            "standard": locator.standard.replace("IFRS ", "").replace("IAS ", ""),
            "paragraph_from": locator.paragraph_from,
            "paragraph_to": locator.paragraph_to,
            "normalized": locator.normalized,
        },
        "confidence": round(max(0.0, min(float(confidence), 1.0)), 2),
        "source_url": source_url,
        "source_type": "AUTHORITATIVE_REFERENCE" if source_url else "USER_SUPPLIED_REFERENCE",
        "official_text_included": False,
        "official_heading_included": False,
        "suggested_cajas_name": _default_cajas_name(locator),
        "suggested_cajas_description": f"{locator.normalized} reference locator for CAJAS-authored judgment review.",
        "name_origin": "CAJAS_AUTHORED",
        "requires_review": True,
        "resolution_reason": reason,
    }


def _default_cajas_name(locator: StandardLocator) -> str:
    if locator.standard == "IFRS 15":
        return "\uc218\uc775 \uacc4\uc57d \ud310\ub2e8 \uae30\uc900 \ucc38\uc870"
    if locator.standard == "IAS 36":
        return "\uc790\uc0b0 \uc190\uc0c1 \ud310\ub2e8 \uae30\uc900 \ucc38\uc870"
    return f"{locator.normalized} CAJAS reference"


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = normalize_reference_code(str(candidate.get("reference_code") or ""))
        current = by_code.get(key)
        if not current or float(candidate.get("confidence") or 0) > float(current.get("confidence") or 0):
            by_code[key] = candidate
    return list(by_code.values())


def _not_found(reason: str) -> dict[str, Any]:
    return {"available": True, "resolved": False, "reason": reason, "requires_manual_reference": True, "candidates": []}
