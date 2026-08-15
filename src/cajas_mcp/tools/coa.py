from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from cajas_mcp.adapters.files import RawFileAdapter
from cajas_mcp.adapters.mapping import infer_coa_column_mapping
from cajas_mcp.auth import resolve_bearer_token, token_binding
from cajas_mcp.client import CajasClient
from cajas_mcp.config import Settings
from cajas_mcp.errors import CajasMcpError, error_payload, ok
from cajas_mcp.import_sessions import IMPORT_SESSION_STORE, ParsedSheet


def register_coa_tools(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="cajas.inspect_coa_file",
        description=(
            "Inspects a CSV/XLSX Chart of Accounts file and proposes CAJAS CoA column mappings. "
            "This tool does not modify any CAJAS CoA profile."
        ),
    )
    async def inspect_coa_file(
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
            coa_sheets = {name: _with_coa_mapping(sheet) for name, sheet in sheets.items()}
            session = IMPORT_SESSION_STORE.create_import(
                actor_binding=token_binding(settings, token),
                file={**file_info, "domain": "coa"},
                sheets=coa_sheets,
                warnings=warnings,
                ttl=settings.import_session_ttl,
            )
            return ok(
                {
                    "import_session_id": session.import_session_id,
                    "org_id": org_id,
                    "file": session.file,
                    "sheets": [_sheet_payload(sheet) for sheet in coa_sheets.values()],
                    "supported_backend_fields": ["code", "name_ko", "name_en"],
                    "ignored_for_import": ["account_type", "level", "parent_code", "is_active", "source_system"],
                    "session_expires_in_seconds": settings.import_session_ttl,
                    "mutation": False,
                },
                warnings=warnings + [warning for sheet in coa_sheets.values() for warning in sheet.warnings],
                explanation="Inspected the CoA file without modifying CAJAS state.",
            )
        except CajasMcpError as exc:
            return error_payload(exc)

    @mcp.tool(
        name="cajas.preview_coa_import",
        description=(
            "Compares a parsed CoA file with a selected CAJAS CoA profile and returns proposed additions, metadata updates, "
            "conflicts, blocked changes, and non-applied deactivate candidates. This tool does not modify the CoA."
        ),
    )
    async def preview_coa_import(
        ctx: Context,
        org_id: str,
        import_session_id: str,
        profile_id: str,
        sheet_name: str | None = None,
        mapping: dict[str, str] | None = None,
    ) -> dict:
        try:
            token = resolve_bearer_token(settings, ctx)
            session = IMPORT_SESSION_STORE.get_import(import_session_id)
            if not session:
                raise CajasMcpError("COA_PREVIEW_EXPIRED", "CoA import session was not found or has expired.", requires_user_action=True)
            actor_binding = token_binding(settings, token)
            if session.actor_binding != actor_binding:
                raise CajasMcpError("PERMISSION_DENIED", "CoA import session belongs to a different authenticated user.", requires_user_action=True)
            sheet = _resolve_sheet(session.sheets, sheet_name)
            column_mapping = mapping or sheet.inferred_mapping
            _validate_coa_mapping(column_mapping)
            normalized_rows = _normalized_coa_rows(sheet.rows, column_mapping)
            payload = {"headers": ["code", "name_ko", "name_en"], "rows": normalized_rows}
            client = CajasClient(settings)
            try:
                preview = await client.preview_coa_import(token=token, org_id=org_id, profile_id=profile_id, payload=payload)
            finally:
                await client.aclose()
            operations = preview.get("operations") or []
            accepted_ids = {
                str(item.get("operation_id"))
                for item in operations
                if item.get("operation") in {"ADD", "UPDATE_METADATA"} and bool(item.get("can_apply"))
            }
            can_import = bool(preview.get("can_import")) and bool(accepted_ids)
            preview_session = IMPORT_SESSION_STORE.create_coa_preview(
                actor_binding=actor_binding,
                import_session_id=import_session_id,
                sheet_name=sheet.name,
                org_id=org_id,
                profile_id=profile_id,
                headers=["code", "name_ko", "name_en"],
                rows=normalized_rows,
                column_mapping=column_mapping,
                backend_preview=preview,
                accepted_operation_ids=accepted_ids,
                can_import=can_import,
                ttl=settings.import_session_ttl,
            )
            return ok(
                {
                    "preview_id": preview_session.preview_id,
                    "profile": preview.get("profile") or {"id": profile_id},
                    "summary": preview.get("summary") or {},
                    "operations": operations,
                    "default_accepted_operation_ids": sorted(accepted_ids),
                    "can_import": can_import,
                    "mutation": False,
                },
                warnings=_preview_warnings(preview),
                explanation="Previewed CoA import through CAJAS backend dry-run without modifying the selected profile.",
                request_id=preview.get("_request_id"),
            )
        except CajasMcpError as exc:
            return error_payload(exc)

    @mcp.tool(
        name="cajas.import_coa",
        description=(
            "Applies explicitly accepted ADD/UPDATE_METADATA operations from a successful CoA import preview. "
            "This tool mutates the selected CAJAS CoA profile. It does not replace the entire CoA or deactivate missing accounts."
        ),
    )
    async def import_coa(
        ctx: Context,
        org_id: str,
        preview_id: str,
        accepted_operation_ids: list[str],
        idempotency_key: str | None = None,
    ) -> dict:
        try:
            token = resolve_bearer_token(settings, ctx)
            preview = IMPORT_SESSION_STORE.get_coa_preview(preview_id)
            if not preview:
                raise CajasMcpError("COA_PREVIEW_EXPIRED", "CoA preview was not found or has expired.", requires_user_action=True)
            actor_binding = token_binding(settings, token)
            if preview.actor_binding != actor_binding:
                raise CajasMcpError("PERMISSION_DENIED", "CoA preview belongs to a different authenticated user.", requires_user_action=True)
            if preview.org_id != org_id:
                raise CajasMcpError("PERMISSION_DENIED", "Preview belongs to a different org context.", requires_user_action=True)
            clean_ids = {str(value).strip() for value in (accepted_operation_ids or []) if str(value).strip()}
            if not clean_ids:
                raise CajasMcpError("COA_PREVIEW_REQUIRED", "accepted_operation_ids is required for CoA import.", requires_user_action=True)
            allowed_ids = set(preview.accepted_operation_ids)
            disallowed = sorted(clean_ids - allowed_ids)
            if disallowed:
                raise CajasMcpError(
                    "COA_BLOCKED_CHANGE",
                    "One or more accepted operations are not applyable ADD/UPDATE_METADATA operations.",
                    requires_user_action=True,
                    details={"operation_ids": disallowed},
                )
            operations = preview.backend_preview.get("operations") or []
            rows_by_op = {
                str(item.get("operation_id")): item.get("incoming")
                for item in operations
                if str(item.get("operation_id")) in clean_ids and isinstance(item.get("incoming"), dict)
            }
            rows = [_upload_row(rows_by_op[op_id]) for op_id in sorted(rows_by_op)]
            if not rows:
                raise CajasMcpError("COA_PREVIEW_REQUIRED", "No accepted operations contain importable rows.", requires_user_action=True)
            cache_key = f"coa:{actor_binding}:{org_id}:{preview_id}:{idempotency_key}" if idempotency_key else ""
            if cache_key:
                cached = IMPORT_SESSION_STORE.get_idempotent_result(cache_key)
                if cached:
                    return ok(cached, explanation="Returned cached CoA import result for the supplied idempotency key.")
            payload = {"headers": ["code", "name_ko", "name_en"], "rows": rows}
            client = CajasClient(settings)
            try:
                result = await client.execute_coa_import(token=token, org_id=org_id, profile_id=preview.profile_id, payload=payload)
            finally:
                await client.aclose()
            output = {
                "mutation": True,
                "profile_id": preview.profile_id,
                "accepted_operation_ids": sorted(clean_ids),
                "added_or_updated_rows": len(rows),
                "added": [row.get("code") for row in rows],
                "updated": [],
                "skipped": [],
                "backend_result": {key: value for key, value in result.items() if key != "_request_id"},
                "next_actions": [
                    {
                        "type": "RERUN_RAW_PREVIEW",
                        "recommended_tool": "cajas.preview_raw_import",
                        "reason": "CoA profile changed; rerun RAW preview to verify previously unresolved accounts.",
                    }
                ],
            }
            if cache_key:
                IMPORT_SESSION_STORE.store_idempotent_result(cache_key, output, settings.import_session_ttl)
            return ok(
                output,
                warnings=[] if idempotency_key else ["IDEMPOTENCY_KEY_RECOMMENDED: provide idempotency_key for safer client retries."],
                explanation="Applied accepted CoA operations through CAJAS profile upload. No profile replace or deactivation was performed.",
                request_id=result.get("_request_id"),
            )
        except CajasMcpError as exc:
            return error_payload(exc)


def _with_coa_mapping(sheet: ParsedSheet) -> ParsedSheet:
    mapping, candidates, warnings = infer_coa_column_mapping(sheet.headers)
    return ParsedSheet(
        name=sheet.name,
        headers=sheet.headers,
        rows=sheet.rows,
        row_count=sheet.row_count,
        column_count=sheet.column_count,
        sample_rows=sheet.sample_rows,
        inferred_mapping=mapping,
        mapping_candidates=candidates,
        warnings=warnings,
    )


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


def _validate_coa_mapping(mapping: dict[str, str]) -> None:
    targets = set((mapping or {}).values())
    missing = []
    if "code" not in targets:
        missing.append("code")
    if not ({"name_ko", "name_en"} & targets):
        missing.append("name_ko/name_en")
    if missing:
        raise CajasMcpError(
            "COA_MAPPING_REQUIRED",
            "CoA column mapping is missing required target fields.",
            requires_user_action=True,
            details={"missing": missing},
        )


def _normalized_coa_rows(rows: list[dict[str, Any]], mapping: dict[str, str]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {"code": None, "name_ko": None, "name_en": None}
        for header, target in (mapping or {}).items():
            if target in item:
                item[target] = row.get(header)
        normalized.append(item)
    return normalized


def _upload_row(incoming: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": str(incoming.get("code") or incoming.get("account_code") or "").strip(),
        "account_code": str(incoming.get("account_code") or incoming.get("code") or "").strip(),
        "name_ko": str(incoming.get("name_ko") or "").strip() or None,
        "name_en": str(incoming.get("name_en") or "").strip() or None,
    }


def _preview_warnings(preview: dict[str, Any]) -> list[str]:
    summary = preview.get("summary") or {}
    warnings: list[str] = []
    if int(summary.get("blocked") or 0):
        warnings.append("COA_BLOCKED_CHANGE: blocked operations must be resolved outside import_coa.")
    if int(summary.get("conflict") or 0):
        warnings.append("COA_CONFLICT: conflicts must be resolved before import.")
    if int(summary.get("deactivate_candidate") or 0):
        warnings.append("DEACTIVATE_CANDIDATE: missing existing accounts are not deactivated by MCP.")
    return warnings
