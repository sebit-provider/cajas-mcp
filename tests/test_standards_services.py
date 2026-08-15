from __future__ import annotations

import unittest

from cajas_mcp.services_standards import (
    criterion_payload,
    find_existing_reference_match,
    propose_criterion_group_payload,
    propose_interpretation_payload,
)


class StandardsServiceTests(unittest.TestCase):
    def test_existing_criterion_exact_and_overlap(self) -> None:
        rows = [
            {
                "id": "std-1",
                "standard_type": "IFRS",
                "code": "IFRS 15.22-30",
                "title": "Revenue obligation reference",
                "level": "L1",
                "is_active": True,
            }
        ]
        exact = find_existing_reference_match(rows, "IFRS15.22-30", "IFRS")
        overlap = find_existing_reference_match(rows, "IFRS 15.27", "IFRS")
        self.assertEqual(exact["match_type"], "EXACT_NORMALIZED_CODE")
        self.assertEqual(overlap["match_type"], "LOCATOR_INCLUDED_IN_EXISTING_RANGE")

    def test_criterion_proposal_blocks_duplicate_and_preserves_provenance(self) -> None:
        candidate = {
            "framework": "IFRS",
            "reference_code": "IFRS 15.22-30",
            "source_url": "https://www.ifrs.org/",
            "source_type": "AUTHORITATIVE_REFERENCE",
            "suggested_cajas_name": "CAJAS authored title",
            "suggested_cajas_description": "CAJAS authored summary.",
        }
        existing = {"match_type": "EXACT_NORMALIZED_CODE", "criterion": criterion_payload({"id": "std-1", "code": "IFRS 15.22-30"})}
        proposal = propose_criterion_group_payload(candidate=candidate, existing_match=existing, requested_level="L1")
        self.assertTrue(proposal["blocked"])
        self.assertEqual(proposal["blocked_reason"], "CRITERION_DUPLICATE_OR_OVERLAP")
        self.assertEqual(proposal["criterion"]["name_origin"], "CAJAS_AUTHORED")
        self.assertFalse(proposal["criterion"]["reference"]["official_text_included"])
        self.assertFalse(proposal["mutation"])

    def test_interpretation_proposal_level_is_independent_from_criterion(self) -> None:
        criterion = criterion_payload({"id": "std-1", "code": "IFRS 15.22-30", "title": "Criterion", "level": "L1"})
        proposal = propose_interpretation_payload(
            criterion_group_id="std-1",
            criterion_group=criterion,
            event_context={"title": "Contract A", "summary": "Specific one-time customer contract review"},
            requested_level="L3",
            similar_existing=[],
        )
        self.assertEqual(proposal["criterion_group"]["criterion_level"]["code"], "L1")
        self.assertEqual(proposal["interpretation"]["interpretation_level"]["code"], "L3")
        self.assertFalse(proposal["requires_level_selection"])
        self.assertFalse(proposal["mutation"])

    def test_interpretation_level_selection_required_when_context_is_ambiguous(self) -> None:
        proposal = propose_interpretation_payload(
            criterion_group_id="std-1",
            criterion_group={"code": "IFRS 15.22-30"},
            event_context={"summary": "Needs review"},
            requested_level=None,
            similar_existing=[],
        )
        self.assertTrue(proposal["requires_level_selection"])


if __name__ == "__main__":
    unittest.main()
