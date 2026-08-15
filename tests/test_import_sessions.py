from __future__ import annotations

import time
import unittest

from cajas_mcp.import_sessions import ImportSessionStore, ParsedSheet


class ImportSessionTests(unittest.TestCase):
    def test_preview_requires_live_import_session(self) -> None:
        store = ImportSessionStore()
        self.assertIsNone(store.get_import("missing"))

    def test_create_preview_and_expire(self) -> None:
        store = ImportSessionStore()
        sheet = ParsedSheet(
            name="Sheet1",
            headers=["date", "account code", "amount"],
            rows=[{"date": "2026-08-01", "account code": "1000", "amount": "10"}],
            row_count=1,
            column_count=3,
            sample_rows=[],
            inferred_mapping={"date": "transaction_date", "account code": "account_code", "amount": "amount"},
            mapping_candidates=[],
        )
        session = store.create_import(file={"name": "x.csv"}, sheets={"Sheet1": sheet}, warnings=[], ttl=1)
        preview = store.create_preview(
            import_session_id=session.import_session_id,
            sheet_name="Sheet1",
            org_id="org",
            profile_id="profile",
            headers=sheet.headers,
            rows=sheet.rows,
            column_mapping=sheet.inferred_mapping,
            voucher_rule={},
            import_shape="erp_line",
            backend_preview={"summary": {"invalid_rows": 0}},
            can_import=True,
            ttl=1,
        )
        self.assertIsNotNone(store.get_preview(preview.preview_id))
        preview.expires_at = time.time() - 1
        self.assertIsNone(store.get_preview(preview.preview_id))

    def test_idempotent_result_cache(self) -> None:
        store = ImportSessionStore()
        store.store_idempotent_result("key", {"created_raw_entry_ids": ["raw-1"]}, ttl=30)
        self.assertEqual(store.get_idempotent_result("key"), {"created_raw_entry_ids": ["raw-1"]})


if __name__ == "__main__":
    unittest.main()
