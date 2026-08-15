from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedSheet:
    name: str
    headers: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    column_count: int
    sample_rows: list[dict[str, Any]]
    inferred_mapping: dict[str, str]
    mapping_candidates: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImportSession:
    import_session_id: str
    file: dict[str, Any]
    sheets: dict[str, ParsedSheet]
    warnings: list[str]
    created_at: float
    expires_at: float


@dataclass
class PreviewSession:
    preview_id: str
    import_session_id: str
    sheet_name: str
    org_id: str
    profile_id: str
    headers: list[str]
    rows: list[dict[str, Any]]
    column_mapping: dict[str, str]
    voucher_rule: dict[str, Any]
    import_shape: str
    backend_preview: dict[str, Any]
    can_import: bool
    created_at: float
    expires_at: float


@dataclass
class CoaPreviewSession:
    preview_id: str
    import_session_id: str
    sheet_name: str
    org_id: str
    profile_id: str
    headers: list[str]
    rows: list[dict[str, Any]]
    column_mapping: dict[str, str]
    backend_preview: dict[str, Any]
    accepted_operation_ids: set[str]
    can_import: bool
    created_at: float
    expires_at: float


class ImportSessionStore:
    def __init__(self) -> None:
        self._imports: dict[str, ImportSession] = {}
        self._previews: dict[str, PreviewSession] = {}
        self._coa_previews: dict[str, CoaPreviewSession] = {}
        self._idempotency: dict[str, dict[str, Any]] = {}

    def create_import(self, *, file: dict[str, Any], sheets: dict[str, ParsedSheet], warnings: list[str], ttl: int) -> ImportSession:
        self.purge_expired()
        now = time.time()
        session = ImportSession(
            import_session_id=f"imp_{uuid.uuid4().hex}",
            file=file,
            sheets=sheets,
            warnings=warnings,
            created_at=now,
            expires_at=now + ttl,
        )
        self._imports[session.import_session_id] = session
        return session

    def get_import(self, import_session_id: str) -> ImportSession | None:
        self.purge_expired()
        return self._imports.get(import_session_id)

    def create_preview(
        self,
        *,
        import_session_id: str,
        sheet_name: str,
        org_id: str,
        profile_id: str,
        headers: list[str],
        rows: list[dict[str, Any]],
        column_mapping: dict[str, str],
        voucher_rule: dict[str, Any],
        import_shape: str,
        backend_preview: dict[str, Any],
        can_import: bool,
        ttl: int,
    ) -> PreviewSession:
        self.purge_expired()
        now = time.time()
        preview = PreviewSession(
            preview_id=f"prv_{uuid.uuid4().hex}",
            import_session_id=import_session_id,
            sheet_name=sheet_name,
            org_id=org_id,
            profile_id=profile_id,
            headers=headers,
            rows=rows,
            column_mapping=column_mapping,
            voucher_rule=voucher_rule,
            import_shape=import_shape,
            backend_preview=backend_preview,
            can_import=can_import,
            created_at=now,
            expires_at=now + ttl,
        )
        self._previews[preview.preview_id] = preview
        return preview

    def get_preview(self, preview_id: str) -> PreviewSession | None:
        self.purge_expired()
        return self._previews.get(preview_id)

    def create_coa_preview(
        self,
        *,
        import_session_id: str,
        sheet_name: str,
        org_id: str,
        profile_id: str,
        headers: list[str],
        rows: list[dict[str, Any]],
        column_mapping: dict[str, str],
        backend_preview: dict[str, Any],
        accepted_operation_ids: set[str],
        can_import: bool,
        ttl: int,
    ) -> CoaPreviewSession:
        self.purge_expired()
        now = time.time()
        preview = CoaPreviewSession(
            preview_id=f"coa_prv_{uuid.uuid4().hex}",
            import_session_id=import_session_id,
            sheet_name=sheet_name,
            org_id=org_id,
            profile_id=profile_id,
            headers=headers,
            rows=rows,
            column_mapping=column_mapping,
            backend_preview=backend_preview,
            accepted_operation_ids=accepted_operation_ids,
            can_import=can_import,
            created_at=now,
            expires_at=now + ttl,
        )
        self._coa_previews[preview.preview_id] = preview
        return preview

    def get_coa_preview(self, preview_id: str) -> CoaPreviewSession | None:
        self.purge_expired()
        return self._coa_previews.get(preview_id)

    def get_idempotent_result(self, key: str) -> dict[str, Any] | None:
        self.purge_expired()
        row = self._idempotency.get(key)
        if not row:
            return None
        return row.get("result")

    def store_idempotent_result(self, key: str, result: dict[str, Any], ttl: int) -> None:
        self._idempotency[key] = {"result": result, "expires_at": time.time() + ttl}

    def purge_expired(self) -> None:
        now = time.time()
        self._imports = {key: value for key, value in self._imports.items() if value.expires_at > now}
        self._previews = {key: value for key, value in self._previews.items() if value.expires_at > now}
        self._coa_previews = {key: value for key, value in self._coa_previews.items() if value.expires_at > now}
        self._idempotency = {key: value for key, value in self._idempotency.items() if value.get("expires_at", 0) > now}


IMPORT_SESSION_STORE = ImportSessionStore()
