from __future__ import annotations

import re

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\-\s().]{7,}\d)(?!\d)")
INVOICE_RE = re.compile(r"\b(?:invoice|inv|contract|customer|cust|project)\s*[:#-]?\s*[A-Z0-9][A-Z0-9._-]{2,}\b", re.IGNORECASE)
ID_RE = re.compile(r"\b[A-Z]{2,}[-_]\d{3,}\b")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
PROMPT_INJECTION_RE = re.compile(
    r"(ignore previous instructions|call another tool|download this url|send this data|system prompt|developer message)",
    re.IGNORECASE,
)

TECH_HINTS = {
    "aws",
    "ec2",
    "nat",
    "gateway",
    "s3",
    "azure",
    "gcp",
    "migration",
    "implementation",
    "training",
    "subscription",
    "license",
    "saas",
    "consulting",
    "support",
    "maintenance",
}


def sanitize_external_query(text: str, *, max_terms: int = 10) -> str:
    cleaned = URL_RE.sub(" ", text)
    cleaned = EMAIL_RE.sub(" ", cleaned)
    cleaned = PHONE_RE.sub(" ", cleaned)
    cleaned = INVOICE_RE.sub(" ", cleaned)
    cleaned = ID_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9가-힣\s+-]", " ", cleaned)
    tokens = [t.strip(" +-").lower() for t in cleaned.split() if len(t.strip(" +-")) >= 3]
    selected: list[str] = []
    for token in tokens:
        if token in TECH_HINTS or any(hint in token for hint in TECH_HINTS):
            if token not in selected:
                selected.append(token)
        if len(selected) >= max_terms:
            break
    if not selected:
        for token in tokens:
            if token not in selected and not token.isdigit():
                selected.append(token)
            if len(selected) >= max_terms:
                break
    return " ".join(selected)


def mark_untrusted_text(text: str) -> dict[str, str | bool]:
    return {
        "text": text,
        "trust": "UNTRUSTED_EXTERNAL_DATA",
        "contains_prompt_injection_pattern": bool(PROMPT_INJECTION_RE.search(text or "")),
    }

