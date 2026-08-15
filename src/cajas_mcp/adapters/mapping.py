from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "voucher_number": ("\uc804\ud45c\ubc88\ud638", "\uc804\ud45c no", "voucher", "voucher no", "voucher_no", "journal no", "document no", "slip no"),
    "transaction_date": ("\uc77c\uc790", "\ub0a0\uc9dc", "\uac70\ub798\uc77c\uc790", "date", "posting date", "transaction date"),
    "line_side": ("\ucc28\ub300", "\ucc28\ubcc0\ub300\ubcc0", "dr/cr", "debit/credit", "side", "dr cr"),
    "account_code": ("\uacc4\uc815\ucf54\ub4dc", "\uacc4\uc815 code", "account code", "acct code", "account_code"),
    "account_name": ("\uacc4\uc815\uba85", "\uacc4\uc815 \uc774\ub984", "account name", "account_name"),
    "account": ("\uacc4\uc815", "account"),
    "debit_amount": ("\ucc28\ubcc0", "\ucc28\ubcc0\uae08\uc561", "debit", "debit amount", "dr amount"),
    "credit_amount": ("\ub300\ubcc0", "\ub300\ubcc0\uae08\uc561", "credit", "credit amount", "cr amount"),
    "amount": ("\uae08\uc561", "amount", "total amount"),
    "description": ("\uc801\uc694", "\ub0b4\uc6a9", "\uba54\ubaa8", "memo", "description", "remarks"),
    "counterparty": ("\uac70\ub798\ucc98", "\uc0c1\ub300\ucc98", "counterparty", "vendor", "customer"),
    "project": ("\ud504\ub85c\uc81d\ud2b8", "project"),
    "department": ("\ubd80\uc11c", "department", "dept"),
    "currency": ("\ud1b5\ud654", "currency"),
}

COA_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "code": (
        "\uacc4\uc815\ucf54\ub4dc",
        "\uacc4\uc815\uacfc\ubaa9\ucf54\ub4dc",
        "account code",
        "account_code",
        "code",
    ),
    "name_ko": (
        "\uacc4\uc815\uba85",
        "\uacc4\uc815\uacfc\ubaa9",
        "\ud55c\uae00\uacc4\uc815\uba85",
        "account name",
        "name",
        "name ko",
        "korean name",
        "name_ko",
    ),
    "name_en": (
        "\uc601\ubb38\uacc4\uc815\uba85",
        "\uc601\ubb38\uba85",
        "english name",
        "name en",
        "name_en",
    ),
    "account_type": ("\uacc4\uc815\uc720\ud615", "account type", "type", "category"),
    "level": ("\ub808\ubca8", "level"),
    "parent_code": ("\uc0c1\uc704\uacc4\uc815\ucf54\ub4dc", "parent code", "parent account code"),
    "is_active": ("\ud65c\uc131", "\uc0ac\uc6a9\uc5ec\ubd80", "is active", "active", "is_active"),
    "source_system": ("source system", "source_system"),
}


@dataclass(frozen=True)
class MappingCandidate:
    column: str
    candidates: list[dict[str, Any]]
    selected_field: str | None
    requires_choice: bool


def normalize_header(value: str) -> str:
    normalized = re.sub(r"[\s_\-()/]+", " ", str(value or "").strip().lower())
    return re.sub(r"\s+", " ", normalized).strip()


def infer_column_mapping(headers: list[str]) -> tuple[dict[str, str], list[dict[str, Any]], list[str]]:
    mapping: dict[str, str] = {}
    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    used_fields: set[str] = set()

    for header in headers:
        scored = _score_header(header)
        requires_choice = False
        selected: str | None = None
        if scored:
            top = scored[0]
            second_score = float(scored[1]["score"]) if len(scored) > 1 else 0.0
            normalized = normalize_header(header)
            ambiguous_account = normalized in {"account", "\uacc4\uc815"}
            requires_choice = ambiguous_account or (
                float(top["score"]) < 1.0 and (float(top["score"]) < 0.75 or float(top["score"]) - second_score < 0.15)
            )
            if not requires_choice and str(top["field"]) not in used_fields:
                selected = str(top["field"])
                mapping[header] = selected
                used_fields.add(selected)
            elif str(top["field"]) in used_fields:
                requires_choice = True
        candidates.append(
            {
                "column": header,
                "candidates": scored,
                "selected_field": selected,
                "requires_choice": requires_choice,
            }
        )

    if "transaction_date" not in mapping.values():
        warnings.append("COLUMN_MAPPING_REQUIRED: transaction_date was not confidently inferred.")
    if not ({"amount", "debit_amount", "credit_amount"} & set(mapping.values())):
        warnings.append("COLUMN_MAPPING_REQUIRED: amount/debit/credit was not confidently inferred.")
    if not ({"account_code", "account_name", "account"} & set(mapping.values())):
        warnings.append("COLUMN_MAPPING_REQUIRED: account field was not confidently inferred.")
    return mapping, candidates, warnings


def infer_coa_column_mapping(headers: list[str]) -> tuple[dict[str, str], list[dict[str, Any]], list[str]]:
    mapping: dict[str, str] = {}
    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    used_fields: set[str] = set()
    for header in headers:
        scored = _score_header_against(header, COA_FIELD_ALIASES)
        selected: str | None = None
        requires_choice = False
        if scored:
            top = scored[0]
            second_score = float(scored[1]["score"]) if len(scored) > 1 else 0.0
            normalized = normalize_header(header)
            ambiguous_name = normalized in {"name", "account name", "\uacc4\uc815\uba85", "\uacc4\uc815\uacfc\ubaa9"}
            requires_choice = ambiguous_name or (
                float(top["score"]) < 1.0 and (float(top["score"]) < 0.75 or float(top["score"]) - second_score < 0.15)
            )
            if str(top["field"]) in {"account_type", "level", "parent_code", "is_active", "source_system"}:
                requires_choice = False
                selected = str(top["field"])
                mapping[header] = selected
                used_fields.add(selected)
            elif not requires_choice and str(top["field"]) not in used_fields:
                selected = str(top["field"])
                mapping[header] = selected
                used_fields.add(selected)
            elif str(top["field"]) in used_fields:
                requires_choice = True
        candidates.append(
            {
                "column": header,
                "candidates": scored,
                "selected_field": selected,
                "requires_choice": requires_choice,
            }
        )
    if "code" not in mapping.values():
        warnings.append("COA_MAPPING_REQUIRED: account code was not confidently inferred.")
    if not ({"name_ko", "name_en"} & set(mapping.values())):
        warnings.append("COA_MAPPING_REQUIRED: at least one display name was not confidently inferred.")
    return mapping, candidates, warnings


def _score_header(header: str) -> list[dict[str, Any]]:
    return _score_header_against(header, FIELD_ALIASES)


def _score_header_against(header: str, aliases_by_field: dict[str, tuple[str, ...]]) -> list[dict[str, Any]]:
    normalized = normalize_header(header)
    scored: list[dict[str, Any]] = []
    if not normalized:
        return scored
    for field, aliases in aliases_by_field.items():
        best = 0.0
        for alias in aliases:
            alias_norm = normalize_header(alias)
            if normalized == alias_norm:
                best = max(best, 1.0)
            elif alias_norm and alias_norm in normalized:
                best = max(best, 0.86)
            elif normalized and normalized in alias_norm:
                best = max(best, 0.68)
        if normalized == "\uacc4\uc815" and field in {"account_code", "account_name", "account"}:
            best = max(best, 0.62 if field != "account" else 0.7)
        if normalized in {"name", "account name", "\uacc4\uc815\uba85", "\uacc4\uc815\uacfc\ubaa9"} and field in {"name_ko", "name_en"}:
            best = max(best, 0.62 if field == "name_en" else 0.7)
        if best:
            scored.append({"field": field, "score": round(best, 2)})
    scored.sort(key=lambda item: float(item["score"]), reverse=True)
    return scored[:4]
