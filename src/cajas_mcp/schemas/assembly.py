from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Signal(BaseModel):
    type: str
    score: float = Field(ge=0.0, le=1.0)
    value: Any = None
    explanation: str = ""
    available: bool = True


class ExternalContextSummary(BaseModel):
    available: bool
    used: bool
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    trust: str = "UNTRUSTED_EXTERNAL_DATA"
    results: list[dict[str, Any]] = Field(default_factory=list)
    warning: str | None = None


class AssemblyCandidate(BaseModel):
    candidate_id: str
    raw_entry_ids: list[str]
    score: float = Field(ge=0.0, le=1.0)
    score_components: dict[str, float] = Field(default_factory=dict)
    signals: list[Signal]
    historical_pattern: dict[str, Any] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    external_context_trigger: dict[str, Any] = Field(default_factory=dict)
    external_context_used: bool = False
    mutation: bool = False


class RecommendAssemblyInput(BaseModel):
    org_id: str
    raw_entry_ids: list[str] = Field(default_factory=list, min_length=1)
    include_external_context: bool = False

    @property
    def unique_raw_entry_ids(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for raw_id in self.raw_entry_ids:
            clean = str(raw_id or "").strip()
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result
