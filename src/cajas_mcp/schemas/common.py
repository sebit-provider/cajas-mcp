from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolEnvelope(BaseModel):
    ok: bool = True
    data: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    explanation: str = ""
    request_id: str | None = None


class ErrorEnvelope(BaseModel):
    ok: Literal[False] = False
    error: dict[str, Any]
    request_id: str | None = None

