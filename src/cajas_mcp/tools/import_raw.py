from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from cajas_mcp.adapters.files import RawFileAdapter
from cajas_mcp.auth import resolve_bearer_token, token_binding
from cajas_mcp.client import CajasClient
from cajas_mcp.config import Settings
from cajas_mcp.errors import CajasMcpError, error_payload, ok
from cajas_mcp.import_sessions import IMPORT_SESSION_STORE, ParsedSheet


def register_import_raw_tools(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="cajas.inspect_raw_file",
        description=(
            "Safely inspects a CSV or XLSX file and returns sheet structure, headers, sample rows, warnings, "
            "and suggested CAJAS Smart Excel column mappings. This tool does not import or modify CAJAS data."
        ),
    )
    async def inspect_raw_file(
        ctx: Context,
        org_id: str,
        file_uri: str | None = None,
        resource_uri: str | None = None,
        file_bytes_base64: str | None = None,
        file_name: str | None = None,
        sample_rows: int = 5,
    ) -> dict:
        try:
            token = resolve_bearer_token(settings, ctx)
            adapter = RawFileAdapter(settings)
            file_info, sheets, warnings = await adapter.inspect(
                ctx=ctx,
                file_uri=file_uri,
                resource_uri=resource_uri,
                file_bytes_base64=file_bytes_base64,
                file_name=file_name,
                sample_rows=sample_rows,
            )
            session = IMPORT_SESSION_STORE.create_import(
                actor_binding=token_binding(settings, token),
                file=file_info,
                sheets=sheets,
                warnings=warnings,
                ttl=settings.import_session_ttl,
            )
            return ok(
                {
                    "import_session_id": session.import_session_id,
                    "org_id": org_id,
                    "file": file_info,
                    "sheets": [_sheet_payload(sheet) for sheet in sheets.values()],
                    "session_expires_in_seconds": settings.import_session_ttl,
                    "mutation": False,
                },
                warnings=warnings + [warning for sheet in sheets.values() for warning in sheet.warnings],
                explanation="Inspected the file without modifying CAJAS state.",
            )
        except CajasMcpError as exc:
            return error_payload(exc)

    @mcp.tool(
        name="cajas.preview_raw_import",
        description=(
            "Validates a previously inspected RAW file sheet against CAJAS Smart Excel import and the selected CoA profile. "
            "Returns unresolved accounts, conflicts, and a non-mutating preview. This tool does not create RAW entries."
        ),
    )
    async def preview_raw_import(
        ctx: Context,
        org_id: str,
        import_session_id: str,
        profile_id: str,
        sheet_name: str | None = None,
        mapping: dict[str, str] | None = None,
        voucher_rule: dict[str, Any] | None = None,
        import_shape: str = "erp_line",
    ) -> dict:
        try:
            token = resolve_bearer_token(settings, ctx)
            session = IMPORT_SESSION_STORE.get_import(import_session_id)
            if not session:
                raise CajasMcpError("PREVIEW_EXPIRED", "Import session was not found or has expired.", requires_user_action=True)
            actor_binding = token_binding(settings, token)
            if session.actor_binding != actor_binding:
                raise CajasMcpError("PERMISSION_DENIED", "Import session belongs to a different authenticated user.", requires_user_action=True)
            sheet = _resolve_sheet(session.sheets, sheet_name)
            column_mapping = mapping or sheet.inferred_mapping
            _validate_mapping(column_mapping)
            payload = {
                "profile_id": profile_id,
                "headers": sheet.headers,
                "rows": sheet.rows,
                "column_mapping": column_mapping,
                "voucher_rule": voucher_rule or {},
                "import_shape": import_shape,
            }
            client = CajasClient(settings)
            try:
                preview = await client.preview_raw_import(token=token, org_id=org_id, payload=payload)
            finally:
                await client.aclose()
            summary = preview.get("summary") or {}
            unresolved = _unresolved_accounts(preview)
            conflicts = _conflicts(preview)
            invalid_rows = int(summary.get("invalid_rows") or 0)
            can_import = invalid_rows == 0 and not unresolved and not conflicts
            preview_session = IMPORT_SESSION_STORE.create_preview(
                actor_binding=actor_binding,
                import_session_id=import_session_id,
                sheet_name=sheet.name,
                org_id=org_id,
                profile_id=profile_id,
                headers=sheet.headers,
                rows=sheet.rows,
                column_mapping=column_mapping,
                voucher_rule=voucher_rule or {},
                import_shape=import_shape,
                backend_preview=preview,
                can_import=can_import,
                ttl=settings.import_session_ttl,
            )
            return ok(
                {
                    "preview_id": preview_session.preview_id,
                    "summary": {
                        "rows": int(summary.get("total_rows") or len(preview.get("rows") or [])),
                        "valid": int(summary.get("valid_rows") or 0),
                        "warnings": len(sheet.warnings),
                        "errors": invalid_rows,
                    },
                    "mapping": column_mapping,
                    "unresolved_accounts": unresolved,
                    "conflicts": conflicts,
                    "sample_preview": _sample_preview(preview),
                    "can_import": can_import,
                    "next_actions": _raw_preview_next_actions(unresolved),
                    "session_expires_in_seconds": settings.import_session_ttl,
                    "mutation": False,
                },
                warnings=sheet.warnings,
                explanation="Previewed RAW import through CAJAS Smart Excel without creating RAW entries.",
                request_id=preview.get("_request_id"),
            )
        except CajasMcpError as exc:
            return error_payload(exc)

    @mcp.tool(
        name="cajas.import_raw_file",
        description=(
            "Imports a previously validated RAW file preview into CAJAS using Smart Excel execute. "
            "This tool mutates CAJAS data by creating RAW entries/groups. It does not create Events, approve, sign, or finalize anything."
        ),
    )
    async def import_raw_file(
        ctx: Context,
        org_id: str,
        preview_id: str,
        idempotency_key: str | None = None,
        mode: str = "smart_merge",
    ) -> dict:
        try:
            token = resolve_bearer_token(settings, ctx)
            preview = IMPORT_SESSION_STORE.get_preview(preview_id)
            if not preview:
                raise CajasMcpError("PREVIEW_EXPIRED", "Preview was not found or has expired.", requires_user_action=True)
            actor_binding = token_binding(settings, token)
            if preview.actor_binding != actor_binding:
                raise CajasMcpError("PERMISSION_DENIED", "Preview belongs to a different authenticated user.", requires_user_action=True)
            if preview.org_id != org_id:
                raise CajasMcpError("PERMISSION_DENIED", "Preview belongs to a different org context.", requires_user_action=True)
            if not preview.can_import:
                raise CajasMcpError("PREVIEW_HAS_ERRORS", "Preview has unresolved errors and cannot be imported.", requires_user_action=True)
            normalized_mode = str(mode or "smart_merge").strip().lower()
            if normalized_mode != "smart_merge":
                raise CajasMcpError(
                    "IMPORT_CONFLICT",
                    "MCP RAW import currently allows only smart_merge mode to avoid destructive replace_all behavior.",
                    requires_user_action=True,
                )
            cache_key = f"{actor_binding}:{org_id}:{preview_id}:{idempotency_key}" if idempotency_key else ""
            if cache_key:
                cached = IMPORT_SESSION_STORE.get_idempotent_result(cache_key)
                if cached:
                    return ok(cached, explanation="Returned cached import result for the supplied idempotency key.")
            payload = {
                "mode": normalized_mode,
                "profile_id": preview.profile_id,
                "headers": preview.headers,
                "rows": preview.rows,
                "column_mapping": preview.column_mapping,
                "voucher_rule": preview.voucher_rule,
                "import_shape": preview.import_shape,
                "save_settings": False,
            }
            client = CajasClient(settings)
            try:
                result = await client.execute_raw_import(token=token, org_id=org_id, payload=payload)
            finally:
                await client.aclose()
            raw_entry_ids = [str(value) for value in (result.get("raw_entry_ids") or []) if str(value)]
            output = {
                "mutation": True,
                "created_raw_entry_ids": raw_entry_ids,
                "created_raw_group_ids": [str(value) for value in (result.get("raw_group_ids") or []) if str(value)],
                "created_transaction_ids": [],
                "raw_created": int(result.get("raw_created") or len(raw_entry_ids)),
                "skipped_existing_vouchers": result.get("skipped_existing_vouchers") or [],
                "summary": result.get("summary") or {},
                "idempotency_key": idempotency_key,
                "next_actions": [{"tool": "cajas.recommend_assembly", "raw_entry_ids": raw_entry_ids}] if raw_entry_ids else [],
            }
            if cache_key:
                IMPORT_SESSION_STORE.store_idempotent_result(cache_key, output, settings.import_session_ttl)
            return ok(
                output,
                warnings=[] if idempotency_key else ["IDEMPOTENCY_KEY_RECOMMENDED: provide idempotency_key for safer client retries."],
                explanation="Imported RAW entries through CAJAS Smart Excel. No Event, approval, signature, or finalization was performed.",
                request_id=result.get("_request_id"),
            )
        except CajasMcpError as exc:
            return error_payload(exc)


def _sheet_payload(sheet: ParsedSheet) -> dict[str, Any]:
    return {
        "name": sheet.name,
        "rows": sheet.row_count,
        "columns": sheet.column_count,
        "headers": sheet.headers,
        "sample_rows": sheet.sample_rows,
        "inferred_mapping": sheet.inferred_mapping,
        "mapping_candidates": sheet.mapping_candidates,
        "warnings": sheet.warnings,
    }


def _resolve_sheet(sheets: dict[str, ParsedSheet], sheet_name: str | None) -> ParsedSheet:
    if sheet_name:
        sheet = sheets.get(sheet_name)
        if not sheet:
            raise CajasMcpError("SHEET_NOT_FOUND", f"Sheet not found: {sheet_name}", requires_user_action=True)
        return sheet
    if len(sheets) == 1:
        return next(iter(sheets.values()))
    raise CajasMcpError("SHEET_NOT_FOUND", "sheet_name is required when the workbook has multiple sheets.", requires_user_action=True)


def _validate_mapping(mapping: dict[str, str]) -> None:
    targets = set(mapping.values())
    missing = []
    if "transaction_date" not in targets:
        missing.append("transaction_date")
    if not ({"account_code", "account_name", "account"} & targets):
        missing.append("account_code/account_name/account")
    if not ({"amount", "debit_amount", "credit_amount"} & targets):
        missing.append("amount/debit_amount/credit_amount")
    if missing:
        raise CajasMcpError(
            "COLUMN_MAPPING_REQUIRED",
            "Column mapping is missing required Smart Excel target fields.",
            requires_user_action=True,
            details={"missing": missing},
        )


def _unresolved_accounts(preview: dict[str, Any]) -> list[dict[str, Any]]:
    unresolved: dict[str, dict[str, Any]] = {}
    for row in preview.get("rows") or []:
        for error in row.get("errors") or []:
            text = str(error)
            if "account" not in text.lower():
                continue
            key = text[:200]
            unresolved[key] = {"status": "UNRESOLVED_COA", "message": text, "requires_user_action": True}
        for line in row.get("lines") or []:
            if not line.get("account_code"):
                source = str(line.get("source_account_code") or line.get("source_account_name") or "").strip()
                key = source or f"row-{row.get('row_index')}-line-{line.get('line_no')}"
                unresolved[key] = {
                    "account": source,
                    "status": "UNRESOLVED_COA",
                    "requires_user_action": True,
                }
    return list(unresolved.values())


def _conflicts(preview: dict[str, Any]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for row in preview.get("rows") or []:
        for error in row.get("errors") or []:
            text = str(error)
            lowered = text.lower()
            if "match" in lowered or "duplicate" in lowered or "conflict" in lowered:
                conflicts.append({"row_index": row.get("row_index"), "message": text})
    return conflicts


def _sample_preview(preview: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    sample: list[dict[str, Any]] = []
    for row in (preview.get("rows") or [])[:limit]:
        sample.append(
            {
                "row_index": row.get("row_index"),
                "voucher_number": row.get("voucher_number"),
                "transaction_date": row.get("transaction_date"),
                "line_count": row.get("line_count"),
                "is_valid": row.get("is_valid"),
                "errors": row.get("errors") or [],
            }
        )
    return sample


def _raw_preview_next_actions(unresolved_accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not unresolved_accounts:
        return []
    return [
        {
            "type": "RESOLVE_COA",
            "recommended_tools": ["cajas.inspect_coa_file", "cajas.preview_coa_import", "cajas.import_coa"],
            "reason": "RAW preview found accounts that do not resolve in the selected CoA profile.",
        }
    ]
