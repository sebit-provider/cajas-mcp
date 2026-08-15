from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class RawSearchInput(BaseModel):
    org_id: str
    status: Literal["draft", "queued", "assembled", "voided"] | None = None
    date_from: date | None = None
    date_to: date | None = None
    coa_profile_id: str | None = None
    project: str | None = None
    department: str | None = None
    counterparty_id: str | None = None
    query: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None


class RawEntry(BaseModel):
    id: str
    tx_date: str | None = None
    entry_date: str | None = None
    description: str | None = None
    memo: str | None = None
    project: str | None = None
    department: str | None = None
    counterparty_id: str | None = None
    counterparty_name: str | None = None
    counterpart_id: str | None = None
    source: str | None = None
    import_batch_id: str | None = None
    event_hint_key: str | None = None
    total_amount: float | None = None
    amount: float | None = None
    debit_account_code: str | None = None
    credit_account_code: str | None = None
    account_codes: list[str] = Field(default_factory=list)
    status: str | None = None
    assembled_event_id: str | None = None
    lines: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_ids(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("counterparty_id") and data.get("counterpart_id"):
                data = {**data, "counterparty_id": data.get("counterpart_id")}
            if not data.get("total_amount") and data.get("amount") is not None:
                data = {**data, "total_amount": data.get("amount")}
        return data
