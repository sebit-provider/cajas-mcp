from __future__ import annotations

import asyncio
import base64
import io
import unittest
import zipfile

from cajas_mcp.adapters.files import RawFileAdapter
from cajas_mcp.config import Settings
from cajas_mcp.errors import CajasMcpError


def _settings(**kwargs: object) -> Settings:
    return Settings(cajas_api_base_url="https://cajas.example.test", cajas_api_bearer_token="token", **kwargs)


def _xlsx(sheets: dict[str, list[list[str]]], *, macro: bool = False) -> bytes:
    rels = []
    sheet_nodes = []
    files: dict[str, str | bytes] = {}
    for idx, (name, rows) in enumerate(sheets.items(), start=1):
        rels.append(
            f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
        )
        sheet_nodes.append(f'<sheet name="{name}" sheetId="{idx}" r:id="rId{idx}"/>')
        files[f"xl/worksheets/sheet{idx}.xml"] = _sheet_xml(rows)
    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    if macro:
        content_type = "application/vnd.ms-excel.sheet.macroEnabled.main+xml"
        files["xl/vbaProject.bin"] = b"macro"
    files["[Content_Types].xml"] = (
        f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        f'<Override PartName="/xl/workbook.xml" ContentType="{content_type}"/></Types>'
    )
    files["xl/workbook.xml"] = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{''.join(sheet_nodes)}</sheets></workbook>"
    )
    files["xl/_rels/workbook.xml.rels"] = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(rels)}</Relationships>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, payload in files.items():
            zf.writestr(path, payload)
    return buf.getvalue()


def _sheet_xml(rows: list[list[str]]) -> str:
    row_xml = []
    for ridx, row in enumerate(rows, start=1):
        cells = []
        for cidx, value in enumerate(row):
            ref = f"{chr(ord('A') + cidx)}{ridx}"
            if str(value).startswith("="):
                cells.append(f'<c r="{ref}"><f>{value[1:]}</f><v></v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>')
        row_xml.append(f'<row r="{ridx}">{"".join(cells)}</row>')
    return '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(row_xml) + "</sheetData></worksheet>"


class FileAdapterTests(unittest.TestCase):
    def test_valid_csv_with_korean_headers(self) -> None:
        voucher = "\uc804\ud45c\ubc88\ud638"
        date = "\uc77c\uc790"
        side = "\ucc28\ub300"
        account_code = "\uacc4\uc815\ucf54\ub4dc"
        amount = "\uae08\uc561"
        memo = "\uc801\uc694"
        data = f"{voucher},{date},{side},{account_code},{amount},{memo}\nV1,2026-08-01,D,1000,10,Test\n".encode()

        async def run() -> tuple[dict, dict, list[str]]:
            return await RawFileAdapter(_settings()).inspect(
                file_bytes_base64=base64.b64encode(data).decode(),
                file_name="journal.csv",
            )

        file_info, sheets, warnings = asyncio.run(run())
        sheet = sheets["Sheet1"]
        self.assertEqual(file_info["type"], "csv")
        self.assertEqual(sheet.row_count, 1)
        self.assertEqual(sheet.inferred_mapping[date], "transaction_date")
        self.assertEqual(sheet.inferred_mapping[side], "line_side")
        self.assertFalse(warnings)

    def test_duplicate_headers_are_deduped(self) -> None:
        data = "date,date,amount\n2026-08-01,2026-08-02,10\n".encode()

        async def run() -> list[str]:
            _, sheets, _ = await RawFileAdapter(_settings()).inspect(
                file_bytes_base64=base64.b64encode(data).decode(),
                file_name="journal.csv",
            )
            return sheets["Sheet1"].headers

        self.assertEqual(asyncio.run(run()), ["date", "date_2", "amount"])

    def test_missing_header_warns(self) -> None:
        async def run() -> list[str]:
            _, sheets, warnings = await RawFileAdapter(_settings()).inspect(
                file_bytes_base64=base64.b64encode(b"\n\n").decode(),
                file_name="empty.csv",
            )
            return warnings + sheets["Sheet1"].warnings

        self.assertTrue(any("MISSING_HEADER" in warning for warning in asyncio.run(run())))

    def test_unsupported_extension_rejected(self) -> None:
        async def run() -> None:
            await RawFileAdapter(_settings()).inspect(file_bytes_base64=base64.b64encode(b"x").decode(), file_name="bad.xlsm")

        with self.assertRaises(CajasMcpError) as caught:
            asyncio.run(run())
        self.assertEqual(caught.exception.code, "INVALID_FILE_TYPE")

    def test_renamed_invalid_xlsx_rejected(self) -> None:
        async def run() -> None:
            await RawFileAdapter(_settings()).inspect(file_bytes_base64=base64.b64encode(b"not zip").decode(), file_name="bad.xlsx")

        with self.assertRaises(CajasMcpError) as caught:
            asyncio.run(run())
        self.assertEqual(caught.exception.code, "INVALID_FILE")

    def test_formula_cells_warn_without_execution(self) -> None:
        data = "date,amount\n2026-08-01,=1+1\n".encode()

        async def run() -> list[str]:
            _, _, warnings = await RawFileAdapter(_settings()).inspect(
                file_bytes_base64=base64.b64encode(data).decode(),
                file_name="journal.csv",
            )
            return warnings

        self.assertTrue(any("FORMULA_LIKE" in warning for warning in asyncio.run(run())))

    def test_valid_xlsx_multiple_sheets(self) -> None:
        payload = _xlsx({"Sheet1": [["date", "account code", "amount"], ["2026-08-01", "1000", "10"]], "Sheet2": [["date"]]})

        async def run() -> dict:
            _, sheets, _ = await RawFileAdapter(_settings()).inspect(
                file_bytes_base64=base64.b64encode(payload).decode(),
                file_name="journal.xlsx",
            )
            return sheets

        sheets = asyncio.run(run())
        self.assertEqual(set(sheets), {"Sheet1", "Sheet2"})
        self.assertEqual(sheets["Sheet1"].inferred_mapping["account code"], "account_code")

    def test_xlsx_macro_rejected(self) -> None:
        async def run() -> None:
            await RawFileAdapter(_settings()).inspect(
                file_bytes_base64=base64.b64encode(_xlsx({"Sheet1": [["date"]]}, macro=True)).decode(),
                file_name="journal.xlsx",
            )

        with self.assertRaises(CajasMcpError) as caught:
            asyncio.run(run())
        self.assertEqual(caught.exception.code, "INVALID_FILE")

    def test_very_long_cell_rejected(self) -> None:
        data = f"date\n{'x' * 10}\n".encode()

        async def run() -> None:
            await RawFileAdapter(_settings(max_cell_length=5)).inspect(
                file_bytes_base64=base64.b64encode(data).decode(),
                file_name="journal.csv",
            )

        with self.assertRaises(CajasMcpError) as caught:
            asyncio.run(run())
        self.assertEqual(caught.exception.code, "INVALID_FILE")


if __name__ == "__main__":
    unittest.main()
