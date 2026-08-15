from __future__ import annotations

import base64
import csv
import io
import re
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

from mcp.server.fastmcp import Context

from cajas_mcp.adapters.mapping import infer_column_mapping
from cajas_mcp.config import Settings
from cajas_mcp.errors import CajasMcpError
from cajas_mcp.import_sessions import ParsedSheet


SUPPORTED_EXTENSIONS = {".csv", ".xlsx"}
REJECTED_EXTENSIONS = {".xls", ".xlsm", ".exe", ".zip", ".pdf"}
NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


class RawFileAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def inspect(
        self,
        *,
        ctx: Context | None = None,
        file_uri: str | None = None,
        resource_uri: str | None = None,
        file_bytes_base64: str | None = None,
        file_name: str | None = None,
        sample_rows: int = 5,
    ) -> tuple[dict[str, Any], dict[str, ParsedSheet], list[str]]:
        data, resolved_name, source = await self._load_bytes(
            ctx=ctx,
            file_uri=file_uri,
            resource_uri=resource_uri,
            file_bytes_base64=file_bytes_base64,
            file_name=file_name,
        )
        size = len(data)
        if size > self.settings.max_file_bytes:
            raise CajasMcpError(
                "FILE_TOO_LARGE",
                f"File exceeds maximum size of {self.settings.max_file_bytes} bytes.",
                requires_user_action=True,
                details={"size_bytes": size, "max_file_bytes": self.settings.max_file_bytes},
            )
        ext = self._validate_extension(resolved_name)
        if ext == ".csv":
            sheets, warnings = self._parse_csv(data, sample_rows=max(0, min(sample_rows, 10)))
        else:
            sheets, warnings = self._parse_xlsx(data, sample_rows=max(0, min(sample_rows, 10)))
        file_info = {"name": resolved_name, "type": ext.lstrip("."), "size_bytes": size, "source": source}
        return file_info, sheets, warnings

    async def _load_bytes(
        self,
        *,
        ctx: Context | None,
        file_uri: str | None,
        resource_uri: str | None,
        file_bytes_base64: str | None,
        file_name: str | None,
    ) -> tuple[bytes, str, str]:
        supplied = [value for value in (file_uri, resource_uri, file_bytes_base64) if value]
        if len(supplied) != 1:
            raise CajasMcpError(
                "INVALID_FILE",
                "Provide exactly one file input: file_uri, resource_uri, or file_bytes_base64.",
                requires_user_action=True,
            )
        if file_bytes_base64:
            if not file_name:
                raise CajasMcpError("INVALID_FILE", "file_name is required with file_bytes_base64.", requires_user_action=True)
            try:
                return base64.b64decode(file_bytes_base64, validate=True), Path(file_name).name, "base64"
            except ValueError as exc:
                raise CajasMcpError("INVALID_FILE", "file_bytes_base64 is not valid base64.", requires_user_action=True) from exc
        if file_uri:
            parsed = urlparse(file_uri)
            if parsed.scheme not in {"", "file"}:
                raise CajasMcpError("INVALID_FILE", "Only local file:// URIs are supported for file_uri.", requires_user_action=True)
            raw_path = unquote(parsed.path if parsed.scheme == "file" else file_uri)
            if re.match(r"^/[A-Za-z]:/", raw_path):
                raw_path = raw_path[1:]
            path = Path(raw_path).expanduser().resolve()
            if not path.exists() or not path.is_file():
                raise CajasMcpError("INVALID_FILE", "File path does not exist or is not a file.", requires_user_action=True)
            return path.read_bytes(), path.name, "file_uri"
        if resource_uri:
            if ctx is None or not hasattr(ctx, "read_resource"):
                raise CajasMcpError("INVALID_FILE", "MCP resource reading is not available in this context.", requires_user_action=True)
            result = await ctx.read_resource(resource_uri)
            data = self._resource_to_bytes(result)
            return data, Path(file_name or resource_uri).name, "resource_uri"
        raise CajasMcpError("INVALID_FILE", "No file input supplied.", requires_user_action=True)

    @staticmethod
    def _resource_to_bytes(result: Any) -> bytes:
        contents = getattr(result, "contents", result)
        if isinstance(contents, list):
            contents = contents[0] if contents else b""
        blob = getattr(contents, "blob", None)
        text = getattr(contents, "text", None)
        if blob is not None:
            return base64.b64decode(blob) if isinstance(blob, str) else bytes(blob)
        if text is not None:
            return str(text).encode("utf-8")
        if isinstance(contents, bytes):
            return contents
        if isinstance(contents, str):
            return contents.encode("utf-8")
        raise CajasMcpError("INVALID_FILE", "Unsupported MCP resource content.", requires_user_action=True)

    def _validate_extension(self, file_name: str) -> str:
        ext = Path(file_name).suffix.lower()
        if ext in REJECTED_EXTENSIONS:
            raise CajasMcpError("INVALID_FILE_TYPE", f"{ext} files are not supported.", requires_user_action=True)
        if ext not in SUPPORTED_EXTENSIONS:
            raise CajasMcpError("INVALID_FILE_TYPE", "Only CSV and XLSX files are supported.", requires_user_action=True)
        return ext

    def _parse_csv(self, data: bytes, *, sample_rows: int) -> tuple[dict[str, ParsedSheet], list[str]]:
        if data.startswith(b"PK\x03\x04"):
            raise CajasMcpError("INVALID_FILE", "CSV file appears to contain a ZIP/XLSX payload.", requires_user_action=True)
        text = self._decode_csv(data)
        rows = list(csv.reader(io.StringIO(text)))
        return {"Sheet1": self._rows_to_sheet("Sheet1", rows, sample_rows=sample_rows)}, self._csv_formula_warnings(rows)

    @staticmethod
    def _decode_csv(data: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "cp949"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise CajasMcpError("INVALID_FILE", "CSV encoding is not supported.", requires_user_action=True)

    def _parse_xlsx(self, data: bytes, *, sample_rows: int) -> tuple[dict[str, ParsedSheet], list[str]]:
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise CajasMcpError("INVALID_FILE", "XLSX file is not a valid ZIP workbook.", requires_user_action=True)
        warnings: list[str] = []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            self._validate_zip_safety(zf, compressed_size=max(len(data), 1))
            names = set(zf.namelist())
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise CajasMcpError("INVALID_FILE", "XLSX workbook metadata is missing.", requires_user_action=True)
            if "xl/vbaProject.bin" in names:
                raise CajasMcpError("INVALID_FILE", "Macro-enabled workbooks are not supported.", requires_user_action=True)
            content_types = zf.read("[Content_Types].xml").decode("utf-8", errors="ignore")
            if "vbaProject" in content_types or "macroEnabled" in content_types:
                raise CajasMcpError("INVALID_FILE", "Macro-enabled workbooks are not supported.", requires_user_action=True)
            shared_strings = self._read_shared_strings(zf) if "xl/sharedStrings.xml" in names else []
            sheet_paths = self._workbook_sheets(zf)
            if len(sheet_paths) > self.settings.max_workbook_sheets:
                raise CajasMcpError("WORKBOOK_TOO_LARGE", "Workbook has too many sheets.", requires_user_action=True)
            sheets: dict[str, ParsedSheet] = {}
            for sheet_name, path in sheet_paths:
                raw_rows, formula_count = self._read_sheet_rows(zf, path, shared_strings)
                if formula_count:
                    warnings.append(f"FORMULA_DETECTED: {sheet_name} contains {formula_count} formula cells; formulas were not executed.")
                sheets[sheet_name] = self._rows_to_sheet(sheet_name, raw_rows, sample_rows=sample_rows)
            return sheets, warnings

    def _validate_zip_safety(self, zf: zipfile.ZipFile, *, compressed_size: int) -> None:
        total = 0
        for info in zf.infolist():
            total += info.file_size
            if info.file_size > self.settings.max_file_bytes * 10:
                raise CajasMcpError("WORKBOOK_TOO_LARGE", "Workbook contains an oversized member.", requires_user_action=True)
            if total > self.settings.max_file_bytes * 20:
                raise CajasMcpError("WORKBOOK_TOO_LARGE", "Workbook uncompressed size is too large.", requires_user_action=True)
        if compressed_size and total / compressed_size > 100:
            raise CajasMcpError("WORKBOOK_TOO_LARGE", "Workbook compression ratio is suspicious.", requires_user_action=True)

    @staticmethod
    def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        values: list[str] = []
        for item in root.findall("main:si", NS):
            parts = [node.text or "" for node in item.findall(".//main:t", NS)]
            values.append("".join(parts))
        return values

    @staticmethod
    def _workbook_sheets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib.get("Id"): rel.attrib.get("Target", "") for rel in rels.findall("pkgrel:Relationship", NS)}
        sheets: list[tuple[str, str]] = []
        for sheet in workbook.findall("main:sheets/main:sheet", NS):
            rel_id = sheet.attrib.get(f"{{{NS['rel']}}}id")
            target = rel_map.get(rel_id, "")
            path = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
            sheets.append((str(sheet.attrib.get("name") or f"Sheet{len(sheets) + 1}"), path.replace("\\", "/")))
        return sheets

    def _read_sheet_rows(self, zf: zipfile.ZipFile, path: str, shared_strings: list[str]) -> tuple[list[list[str]], int]:
        root = ET.fromstring(zf.read(path))
        rows: list[list[str]] = []
        formula_count = 0
        for row in root.findall(".//main:sheetData/main:row", NS):
            values: dict[int, str] = {}
            for cell in row.findall("main:c", NS):
                col_idx = self._column_index(cell.attrib.get("r", ""))
                formula = cell.find("main:f", NS)
                if formula is not None:
                    formula_count += 1
                values[col_idx] = self._cell_value(cell, shared_strings)
            if values:
                width = max(values) + 1
                rows.append([values.get(idx, "") for idx in range(width)])
            else:
                rows.append([])
        return rows, formula_count

    @staticmethod
    def _column_index(ref: str) -> int:
        letters = re.sub(r"[^A-Za-z]", "", ref).upper()
        value = 0
        for char in letters:
            value = value * 26 + (ord(char) - ord("A") + 1)
        return max(0, value - 1)

    @staticmethod
    def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            return "".join(node.text or "" for node in cell.findall(".//main:t", NS))
        value_node = cell.find("main:v", NS)
        value = value_node.text if value_node is not None else ""
        if cell_type == "s":
            try:
                return shared_strings[int(value)]
            except (ValueError, IndexError):
                return ""
        return value or ""

    def _rows_to_sheet(self, name: str, rows: list[list[Any]], *, sample_rows: int) -> ParsedSheet:
        first_idx = next((idx for idx, row in enumerate(rows) if any(str(cell).strip() for cell in row)), None)
        if first_idx is None:
            headers: list[str] = []
            data_rows: list[dict[str, Any]] = []
        else:
            headers = self._dedupe_headers([self._safe_cell(cell) for cell in rows[first_idx]])
            data_rows = [self._row_dict(headers, row) for row in rows[first_idx + 1 :] if any(str(cell).strip() for cell in row)]
        if len(headers) > self.settings.max_columns:
            raise CajasMcpError("WORKBOOK_TOO_LARGE", "Sheet has too many columns.", requires_user_action=True)
        if len(data_rows) > self.settings.max_rows:
            raise CajasMcpError("WORKBOOK_TOO_LARGE", "Sheet has too many rows.", requires_user_action=True)
        mapping, candidates, mapping_warnings = infer_column_mapping(headers)
        warnings = list(mapping_warnings)
        if not headers:
            warnings.append("MISSING_HEADER: sheet has no detectable header row.")
        return ParsedSheet(
            name=name,
            headers=headers,
            rows=data_rows,
            row_count=len(data_rows),
            column_count=len(headers),
            sample_rows=data_rows[:sample_rows],
            inferred_mapping=mapping,
            mapping_candidates=candidates,
            warnings=warnings,
        )

    def _safe_cell(self, value: Any) -> str:
        text = str(value or "").strip()
        if len(text) > self.settings.max_cell_length:
            raise CajasMcpError("INVALID_FILE", "Cell exceeds maximum allowed length.", requires_user_action=True)
        return text

    def _row_dict(self, headers: list[str], row: list[Any]) -> dict[str, Any]:
        return {header: self._safe_cell(row[idx]) if idx < len(row) else "" for idx, header in enumerate(headers)}

    @staticmethod
    def _dedupe_headers(headers: list[str]) -> list[str]:
        result: list[str] = []
        seen: dict[str, int] = {}
        for idx, header in enumerate(headers):
            name = header or f"column_{idx + 1}"
            count = seen.get(name, 0)
            seen[name] = count + 1
            result.append(name if count == 0 else f"{name}_{count + 1}")
        return result

    @staticmethod
    def _csv_formula_warnings(rows: list[list[str]]) -> list[str]:
        count = 0
        for row in rows[1:]:
            for value in row:
                text = str(value or "").strip()
                if text.startswith(("=", "@")) or (text.startswith(("+", "-")) and not _is_number(text)):
                    count += 1
        return [f"FORMULA_LIKE_CELL_DETECTED: CSV contains {count} formula-like cells; formulas were not executed."] if count else []


def _is_number(text: str) -> bool:
    try:
        float(text.replace(",", ""))
        return True
    except ValueError:
        return False
