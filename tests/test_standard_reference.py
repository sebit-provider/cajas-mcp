from __future__ import annotations

import asyncio
import unittest

from cajas_mcp.adapters.standard_reference import (
    DeterministicIFRSReferenceProvider,
    extract_standard_locators,
    locator_includes,
    normalize_reference_code,
    sanitize_standard_query,
)


class StandardReferenceTests(unittest.TestCase):
    def test_explicit_locator_is_normalized(self) -> None:
        locators = extract_standard_locators("Review IFRS15.22-30 and IAS 36 paragraph 9.")
        self.assertEqual(locators[0].normalized, "IFRS 15.22-30")
        self.assertEqual(normalize_reference_code("IFRS 15 ¶22-30"), "IFRS 15.22-30")

    def test_overlapping_locator_detected(self) -> None:
        self.assertTrue(locator_includes("IFRS 15.22-30", "IFRS 15.27"))
        self.assertFalse(locator_includes("IFRS 15.22-30", "IFRS 15.31"))
        self.assertFalse(locator_includes("IAS 36.9-14", "IFRS 15.27"))

    def test_topic_resolution_does_not_include_official_text(self) -> None:
        async def run() -> dict:
            provider = DeterministicIFRSReferenceProvider()
            return await provider.resolve(framework="IFRS", query="SaaS migration performance obligation distinct service")

        result = asyncio.run(run())
        self.assertTrue(result["resolved"])
        candidate = result["candidates"][0]
        self.assertEqual(candidate["reference_code"], "IFRS 15.22-30")
        self.assertFalse(candidate["official_text_included"])
        self.assertFalse(candidate["official_heading_included"])
        self.assertEqual(candidate["name_origin"], "CAJAS_AUTHORED")

    def test_no_hallucinated_locator_when_unmatched(self) -> None:
        async def run() -> dict:
            provider = DeterministicIFRSReferenceProvider()
            return await provider.resolve(framework="IFRS", query="office snacks printer toner")

        result = asyncio.run(run())
        self.assertFalse(result["resolved"])
        self.assertTrue(result["requires_manual_reference"])
        self.assertEqual(result["candidates"], [])

    def test_query_sanitization_removes_sensitive_identifiers(self) -> None:
        clean = sanitize_standard_query(
            "Customer ABC Corp contract 2026-102 invoice INV-9912 john@example.com amount 120000 "
            "SaaS migration performance obligation"
        )
        self.assertIn("saas", clean)
        self.assertIn("migration", clean)
        self.assertNotIn("john@example.com", clean)
        self.assertNotIn("INV-9912", clean)
        self.assertNotIn("120000", clean)


if __name__ == "__main__":
    unittest.main()
