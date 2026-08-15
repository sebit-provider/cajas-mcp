from __future__ import annotations

import re
import uuid
from typing import Any

from cajas_mcp.adapters.standard_reference import level_payload, locator_includes, normalize_reference_code


NAME_ORIGIN_CAJAS = "CAJAS_AUTHORED"


def criterion_payload(row: dict[str, Any]) -> dict[str, Any]:
    level = str(row.get("level") or "L2").upper()
    return {
        "id": str(row.get("id") or ""),
        "standard_type": str(row.get("standard_type") or ""),
        "code": str(row.get("code") or ""),
        "name": str(row.get("title") or ""),
        "title": str(row.get("title") or ""),
        "description": str(row.get("description") or ""),
        "level": level_payload(level),
        "criterion_level": level_payload(level),
        "name_origin": _name_origin(row),
        "locked": bool(row.get("locked")),
        "is_active": bool(row.get("is_active", True)),
        "template_count": int(row.get("template_count") or 0),
    }


def find_existing_reference_match(rows: list[dict[str, Any]], reference_code: str, standard_type: str | None = None) -> dict[str, Any] | None:
    normalized = normalize_reference_code(reference_code)
    st = str(standard_type or "").strip().upper()
    for row in rows:
        if st and str(row.get("standard_type") or "").strip().upper() not in {st, "IFRS"}:
            continue
        existing_code = str(row.get("code") or "")
        if normalize_reference_code(existing_code) == normalized:
            return {"match_type": "EXACT_NORMALIZED_CODE", "criterion": criterion_payload(row)}
        if locator_includes(existing_code, reference_code):
            return {"match_type": "LOCATOR_INCLUDED_IN_EXISTING_RANGE", "criterion": criterion_payload(row)}
    return None


def propose_criterion_group_payload(
    *,
    candidate: dict[str, Any],
    existing_match: dict[str, Any] | None,
    requested_level: str = "L1",
) -> dict[str, Any]:
    level = str(requested_level or "L1").upper()
    reference_code = str(candidate.get("reference_code") or "").strip()
    blocked = existing_match is not None
    return {
        "proposal_id": f"crit_prop_{uuid.uuid4().hex}",
        "existing_group_match": bool(existing_match),
        "existing_match": existing_match,
        "criterion": {
            "standard_type": str(candidate.get("framework") or "IFRS").upper(),
            "code": reference_code,
            "title": str(candidate.get("suggested_cajas_name") or _fallback_title(reference_code)),
            "description": str(candidate.get("suggested_cajas_description") or f"{reference_code} reference locator for CAJAS judgment review."),
            "level": level,
            "criterion_level": level_payload(level),
            "name_origin": NAME_ORIGIN_CAJAS,
            "reference": {
                "code": reference_code,
                "source_url": candidate.get("source_url"),
                "source_type": candidate.get("source_type") or "AUTHORITATIVE_REFERENCE",
                "official_text_included": False,
                "official_heading_included": False,
            },
        },
        "blocked": blocked,
        "blocked_reason": "CRITERION_DUPLICATE_OR_OVERLAP" if blocked else None,
        "mutation": False,
        "requires_review": True,
        "next_actions": [
            {
                "type": "CREATE_CRITERION_GROUP",
                "requires_user_approval": True,
                "enabled_in_this_phase": False,
            }
        ],
    }


def interpretation_payload(row: dict[str, Any]) -> dict[str, Any]:
    level = str(row.get("level") or "").upper()
    body = str(row.get("text") or row.get("template_body") or "")
    return {
        "id": str(row.get("id") or ""),
        "criterion_group_id": str(row.get("group_id") or row.get("standard_id") or ""),
        "level": level_payload(level),
        "interpretation_level": level_payload(level),
        "title": str(row.get("title") or ""),
        "body_summary": _summary(body),
        "approval_status": str(row.get("approval_status") or ""),
        "is_active": bool(row.get("is_active", True)),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def propose_interpretation_payload(
    *,
    criterion_group_id: str,
    criterion_group: dict[str, Any] | None,
    event_context: dict[str, Any] | None,
    requested_level: str | None,
    similar_existing: list[dict[str, Any]],
) -> dict[str, Any]:
    inferred_level, requires_level_selection = _infer_interpretation_level(event_context, requested_level)
    title = _interpretation_title(criterion_group=criterion_group, event_context=event_context, level=inferred_level)
    content = _interpretation_content(criterion_group=criterion_group, event_context=event_context, level=inferred_level)
    return {
        "proposal_id": f"interp_prop_{uuid.uuid4().hex}",
        "criterion_group_id": criterion_group_id,
        "criterion_group": criterion_group,
        "interpretation": {
            "level": inferred_level,
            "interpretation_level": level_payload(inferred_level),
            "title": title,
            "content": content,
        },
        "similar_existing": similar_existing,
        "requires_level_selection": requires_level_selection,
        "mutation": False,
        "requires_review": True,
        "next_actions": [
            {
                "type": "CREATE_INTERPRETATION",
                "requires_user_approval": True,
                "enabled_in_this_phase": False,
            }
        ],
    }


def _name_origin(row: dict[str, Any]) -> str:
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    origin = str(meta.get("name_origin") or "").strip().upper()
    return origin if origin in {"CAJAS_AUTHORED", "USER_AUTHORED", "INTERNAL_POLICY", "OFFICIAL"} else NAME_ORIGIN_CAJAS


def _fallback_title(reference_code: str) -> str:
    return f"{reference_code} CAJAS criterion"


def _summary(text: str, limit: int = 280) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    return clean[:limit] + ("..." if len(clean) > limit else "")


def _infer_interpretation_level(event_context: dict[str, Any] | None, requested_level: str | None) -> tuple[str, bool]:
    if requested_level:
        level = str(requested_level).strip().upper()
        if level in {"L1", "L2", "L3"}:
            return level, False
    text = " ".join(str((event_context or {}).get(key) or "") for key in ("title", "summary", "judgment_question")).lower()
    if any(word in text for word in ("policy", "repeat", "recurring", "consistent")):
        return "L2", False
    if any(word in text for word in ("contract", "event", "specific", "one-time", "temporary")):
        return "L3", False
    return "L3", True


def _interpretation_title(*, criterion_group: dict[str, Any] | None, event_context: dict[str, Any] | None, level: str) -> str:
    group_code = str((criterion_group or {}).get("code") or "").strip()
    event_title = str((event_context or {}).get("title") or "").strip()
    if level == "L2":
        return f"{group_code} internal application policy".strip()
    if event_title:
        return f"{event_title} judgment interpretation"
    return f"{group_code} event-specific interpretation".strip()


def _interpretation_content(*, criterion_group: dict[str, Any] | None, event_context: dict[str, Any] | None, level: str) -> str:
    group_code = str((criterion_group or {}).get("code") or "").strip()
    question = str((event_context or {}).get("judgment_question") or (event_context or {}).get("summary") or "").strip()
    scope = "internal recurring policy" if level == "L2" else "event-specific judgment"
    return (
        f"Draft CAJAS-authored {scope} for reference {group_code or 'the selected criterion group'}. "
        f"Judgment context: {_summary(question, 500) or 'to be supplied by reviewer'}. "
        "This proposal is not an accounting approval and requires human review."
    )
