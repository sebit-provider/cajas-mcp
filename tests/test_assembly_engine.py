from __future__ import annotations

import asyncio
import unittest

from cajas_mcp.adapters.external_context import ExternalSearchResult
from cajas_mcp.services import AssemblyRecommendationEngine


class FakeExternalProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: str, *, limit: int = 5) -> list[ExternalSearchResult]:
        self.calls += 1
        return [
            ExternalSearchResult(
                provider="fake",
                title="AWS billing components",
                url="https://example.test/aws",
                summary="aws ec2 nat gateway billing",
                tags=["aws", "ec2", "nat-gateway"],
                score=12,
                accepted_answer=True,
            )
        ]

    async def extract_work_patterns(self, results: list[ExternalSearchResult]) -> list[str]:
        return ["AWS infrastructure billing items can relate to one service environment."]


def raw(
    raw_id: str,
    *,
    project: str = "Phoenix",
    department: str = "IT",
    counterparty_id: str = "cp_1",
    tx_date: str = "2026-08-01",
    description: str = "AWS EC2 NAT Gateway monthly charge",
    amount: float = 100.0,
    import_batch_id: str = "batch_1",
    source: str = "erp",
    debit_account_code: str = "5300",
    credit_account_code: str = "2100",
    status: str = "draft",
    assembled_event_id: str | None = None,
    account_codes: list[str] | None = None,
) -> dict:
    return {
        "id": raw_id,
        "project": project,
        "department": department,
        "counterparty_id": counterparty_id,
        "tx_date": tx_date,
        "description": description,
        "total_amount": amount,
        "import_batch_id": import_batch_id,
        "source": source,
        "debit_account_code": debit_account_code,
        "credit_account_code": credit_account_code,
        "status": status,
        "assembled_event_id": assembled_event_id,
        "account_codes": account_codes or [],
    }


class AssemblyEngineTests(unittest.TestCase):
    def test_same_project_and_counterparty_increase_score(self) -> None:
        engine = AssemblyRecommendationEngine()
        result = asyncio.run(engine.recommend([raw("a"), raw("b", amount=120)], include_external_context=False))
        candidate = result["candidates"][0]
        self.assertGreater(candidate["score"], 0.7)
        signals = {signal["type"]: signal for signal in candidate["signals"]}
        self.assertEqual(signals["same_project"]["score"], 1.0)
        self.assertEqual(signals["same_counterparty"]["score"], 1.0)
        self.assertFalse(candidate["mutation"])

    def test_large_date_gap_decreases_score(self) -> None:
        engine = AssemblyRecommendationEngine()
        near = asyncio.run(engine.recommend([raw("a"), raw("b", tx_date="2026-08-03")], include_external_context=False))
        far = asyncio.run(engine.recommend([raw("a"), raw("b", tx_date="2026-12-30")], include_external_context=False))
        self.assertGreater(near["candidates"][0]["score"], far["candidates"][0]["score"])

    def test_unrelated_raw_splits_candidates(self) -> None:
        engine = AssemblyRecommendationEngine(cluster_threshold=0.55)
        result = asyncio.run(
            engine.recommend(
                [
                    raw("a"),
                    raw("b"),
                    raw("c", project="Other", department="HR", counterparty_id="cp_9", description="Office catering", source="manual"),
                ],
                include_external_context=False,
            )
        )
        candidate_sets = [set(candidate["raw_entry_ids"]) for candidate in result["candidates"]]
        self.assertIn({"a", "b"}, candidate_sets)
        self.assertIn({"c"}, candidate_sets)

    def test_score_stays_within_range(self) -> None:
        engine = AssemblyRecommendationEngine()
        result = asyncio.run(engine.recommend([raw("a"), raw("b")], include_external_context=False))
        for candidate in result["candidates"]:
            self.assertGreaterEqual(candidate["score"], 0.0)
            self.assertLessEqual(candidate["score"], 1.0)

    def test_external_context_cannot_dominate(self) -> None:
        engine = AssemblyRecommendationEngine(external_provider=FakeExternalProvider())
        result = asyncio.run(
            engine.recommend(
                [
                    raw("a", project="A", counterparty_id="cp_1", tx_date="2026-01-01", description="AWS EC2 compute"),
                    raw("b", project="B", counterparty_id="cp_2", tx_date="2026-08-01", description="NAT gateway transfer"),
                ],
                include_external_context=True,
            )
        )
        candidate = result["candidates"][0]
        signals = {signal["type"]: signal for signal in candidate["signals"]}
        self.assertLessEqual(signals["external_context"]["score"], 0.6)
        self.assertLess(candidate["score"], 0.7)

    def test_identical_past_pattern_increases_historical_score(self) -> None:
        engine = AssemblyRecommendationEngine()
        history = [
            {
                "group_id": "group-1",
                "status": "assembled",
                "raw_entries": [
                    {**raw("h1"), "account_codes": ["5300", "2100"]},
                    {**raw("h2", amount=120), "account_codes": ["5300", "2100"]},
                ],
                "has_valid_signature": True,
                "event": {"state": "confirmed", "confirmed_at": "2026-08-02T00:00:00Z"},
            }
        ]
        result = asyncio.run(engine.recommend([raw("a"), raw("b", amount=120)], include_external_context=False, historical_groups=history, history_available=True))
        candidate = result["candidates"][0]
        self.assertGreater(candidate["score_components"]["historical"], 0.7)
        self.assertGreater(candidate["historical_pattern"]["positive_matches"], 0)
        self.assertIn("historical", candidate["score_components"])

    def test_repeated_positive_matches_increase_support(self) -> None:
        engine = AssemblyRecommendationEngine()
        one_history = [{"group_id": "g1", "raw_entries": [raw("h1"), raw("h2")]}]
        repeated_history = [{"group_id": f"g{i}", "raw_entries": [raw(f"h{i}a"), raw(f"h{i}b")]} for i in range(5)]
        one = asyncio.run(engine.recommend([raw("a"), raw("b")], include_external_context=False, historical_groups=one_history, history_available=True))
        repeated = asyncio.run(engine.recommend([raw("a"), raw("b")], include_external_context=False, historical_groups=repeated_history, history_available=True))
        self.assertGreater(repeated["candidates"][0]["score_components"]["historical"], one["candidates"][0]["score_components"]["historical"])

    def test_counterexamples_reduce_support(self) -> None:
        engine = AssemblyRecommendationEngine()
        positive = [{"group_id": "g1", "raw_entries": [raw("h1"), raw("h2")]}]
        with_counterexample = positive + [
            {
                "group_id": "g2",
                "raw_entries": [
                    raw(
                        "x1",
                        department="Legal",
                        description="Unrelated legal advisory",
                        source="manual",
                        amount=900,
                        debit_account_code="9999",
                        credit_account_code="8888",
                    ),
                ],
            }
        ]
        clean = asyncio.run(engine.recommend([raw("a"), raw("b")], include_external_context=False, historical_groups=positive, history_available=True))
        penalized = asyncio.run(engine.recommend([raw("a"), raw("b")], include_external_context=False, historical_groups=with_counterexample, history_available=True))
        self.assertGreater(clean["candidates"][0]["score_components"]["historical"], penalized["candidates"][0]["score_components"]["historical"])
        self.assertGreater(penalized["candidates"][0]["historical_pattern"]["counterexamples"], 0)

    def test_history_exists_but_no_match_returns_low_historical_score(self) -> None:
        engine = AssemblyRecommendationEngine()
        history = [{"group_id": "g1", "raw_entries": [raw("h1", project="Other", counterparty_id="cp-x", description="Office catering")]}]
        result = asyncio.run(engine.recommend([raw("a"), raw("b")], include_external_context=False, historical_groups=history, history_available=True))
        self.assertEqual(result["candidates"][0]["historical_pattern"]["matched_groups"], 0)
        self.assertEqual(result["candidates"][0]["score_components"]["historical"], 0.0)

    def test_historical_score_cannot_dominate_intrinsic_structure(self) -> None:
        engine = AssemblyRecommendationEngine()
        history = [{"group_id": f"g{i}", "raw_entries": [raw(f"h{i}a"), raw(f"h{i}b")]} for i in range(10)]
        result = asyncio.run(
            engine.recommend(
                [
                    raw("a", project="A", counterparty_id="cp-1", description="Service implementation"),
                    raw("b", project="B", counterparty_id="cp-2", description="Office catering"),
                ],
                include_external_context=False,
                historical_groups=history,
                history_available=True,
            )
        )
        candidate = result["candidates"][0]
        self.assertLessEqual(candidate["score"], candidate["score_components"]["intrinsic"] * 0.70 + 0.30)

    def test_strong_intrinsic_and_history_skips_external_search(self) -> None:
        provider = FakeExternalProvider()
        engine = AssemblyRecommendationEngine(external_provider=provider)
        history = [{"group_id": "g1", "raw_entries": [raw("h1", description="Monthly service fee"), raw("h2", description="Monthly service support")]}]
        result = asyncio.run(
            engine.recommend(
                [raw("a", description="Monthly service fee"), raw("b", description="Monthly service support")],
                include_external_context=True,
                historical_groups=history,
                history_available=True,
            )
        )
        self.assertEqual(provider.calls, 0)
        self.assertEqual(result["candidates"][0]["external_context_trigger"]["reason"], "INTERNAL_CONFIDENCE_SUFFICIENT")

    def test_weak_internal_confidence_may_trigger_external_search(self) -> None:
        provider = FakeExternalProvider()
        engine = AssemblyRecommendationEngine(external_provider=provider)
        result = asyncio.run(
            engine.recommend(
                [
                    raw("a", project="A", counterparty_id="cp-1", tx_date="2026-01-01", description="Implementation kickoff"),
                    raw("b", project="B", counterparty_id="cp-2", tx_date="2026-08-01", description="Migration support"),
                ],
                include_external_context=True,
                historical_groups=[],
                history_available=True,
            )
        )
        self.assertGreaterEqual(provider.calls, 1)
        self.assertTrue(result["candidates"][0]["external_context_trigger"]["used"])

    def test_existing_judgment_perfect_agreement(self) -> None:
        engine = AssemblyRecommendationEngine()
        result = asyncio.run(
            engine.recommend(
                [
                    raw("a", assembled_event_id="event-1", status="assembled"),
                    raw("b", assembled_event_id="event-1", status="assembled", amount=120),
                    raw(
                        "c",
                        project="Other",
                        department="Ops",
                        counterparty_id="cp-2",
                        assembled_event_id="event-2",
                        status="assembled",
                        description="Office catering",
                        source="manual",
                        import_batch_id="batch_2",
                        debit_account_code="6100",
                        credit_account_code="1100",
                    ),
                    raw(
                        "d",
                        project="Other",
                        department="Ops",
                        counterparty_id="cp-2",
                        assembled_event_id="event-2",
                        status="assembled",
                        amount=130,
                        description="Office catering support",
                        source="manual",
                        import_batch_id="batch_2",
                        debit_account_code="6100",
                        credit_account_code="1100",
                    ),
                ],
                include_external_context=False,
            )
        )
        comparison = result["existing_judgment_comparison"]
        self.assertTrue(comparison["available"])
        self.assertEqual(comparison["classification"], "AGREEMENT")
        self.assertEqual(comparison["agreement_score"], 1.0)
        self.assertFalse(comparison["review_signal"]["recommended"])

    def test_existing_judgment_suggested_split(self) -> None:
        engine = AssemblyRecommendationEngine(cluster_threshold=0.55)
        result = asyncio.run(
            engine.recommend(
                [
                    raw("a", assembled_event_id="event-1", status="assembled"),
                    raw("b", assembled_event_id="event-1", status="assembled", description="AWS NAT Gateway monthly charge"),
                    raw("c", assembled_event_id="event-1", status="assembled", project="Other", department="HR", counterparty_id="cp-9", description="Office catering"),
                    raw("d", assembled_event_id="event-1", status="assembled", project="Legal", department="Legal", counterparty_id="cp-8", description="Legal advisory"),
                ],
                include_external_context=False,
            )
        )
        comparison = result["existing_judgment_comparison"]
        self.assertEqual(comparison["classification"], "SUGGESTED_SPLIT")
        self.assertTrue(comparison["disagreement"])
        self.assertTrue(any(w["code"] == "EXISTING_ASSEMBLY_REVIEW_SIGNAL" for w in result["warnings"]))

    def test_existing_judgment_suggested_merge(self) -> None:
        engine = AssemblyRecommendationEngine()
        result = asyncio.run(
            engine.recommend(
                [
                    raw("a", assembled_event_id="event-1", status="assembled"),
                    raw("b", assembled_event_id="event-1", status="assembled", amount=120),
                    raw("c", assembled_event_id="event-2", status="assembled", amount=130),
                    raw("d", assembled_event_id="event-2", status="assembled", amount=140),
                ],
                include_external_context=False,
            )
        )
        self.assertEqual(result["existing_judgment_comparison"]["classification"], "SUGGESTED_MERGE")

    def test_existing_judgment_partial_overlap(self) -> None:
        engine = AssemblyRecommendationEngine(cluster_threshold=0.55)
        result = asyncio.run(
            engine.recommend(
                [
                    raw("a", assembled_event_id="event-1", status="assembled", project="P", counterparty_id="cp-1"),
                    raw("b", assembled_event_id="event-1", status="assembled", project="P", counterparty_id="cp-1", amount=120),
                    raw("c", assembled_event_id="event-1", status="assembled", project="Q", counterparty_id="cp-2", description="Training"),
                    raw("d", assembled_event_id="event-2", status="assembled", project="Q", counterparty_id="cp-2", description="Training support"),
                ],
                include_external_context=False,
            )
        )
        self.assertEqual(result["existing_judgment_comparison"]["classification"], "PARTIAL_OVERLAP")

    def test_governance_quality_strengthens_confirmed_history(self) -> None:
        engine = AssemblyRecommendationEngine()
        confirmed = [
            {
                "group_id": "confirmed",
                "status": "assembled",
                "raw_entries": [raw("h1"), raw("h2")],
                "has_valid_signature": True,
                "event": {"state": "confirmed", "confirmed_at": "2026-08-02T00:00:00Z"},
            }
        ]
        oriented = [
            {
                "group_id": "oriented",
                "status": "assembled",
                "raw_entries": [raw("h1"), raw("h2")],
                "event": {"state": "oriented", "confirmed_at": None},
            }
        ]
        confirmed_result = asyncio.run(engine.recommend([raw("a"), raw("b")], include_external_context=False, historical_groups=confirmed, history_available=True))
        oriented_result = asyncio.run(engine.recommend([raw("a"), raw("b")], include_external_context=False, historical_groups=oriented, history_available=True))
        self.assertGreater(
            confirmed_result["candidates"][0]["historical_pattern"]["governance_quality"],
            oriented_result["candidates"][0]["historical_pattern"]["governance_quality"],
        )
        self.assertGreater(
            confirmed_result["candidates"][0]["score_components"]["historical"],
            oriented_result["candidates"][0]["score_components"]["historical"],
        )

    def test_missing_project_department_is_unavailable_not_different(self) -> None:
        engine = AssemblyRecommendationEngine()
        result = asyncio.run(
            engine.recommend(
                [
                    raw("a", project="", department=""),
                    raw("b", project="", department="", amount=120),
                ],
                include_external_context=False,
            )
        )
        signals = {signal["type"]: signal for signal in result["candidates"][0]["signals"]}
        self.assertFalse(signals["same_project"]["available"])
        self.assertFalse(signals["same_department"]["available"])

    def test_revenue_collection_relationship_survives_missing_project_department(self) -> None:
        engine = AssemblyRecommendationEngine(cluster_threshold=0.42)
        result = asyncio.run(
            engine.recommend(
                [
                    raw(
                        "a",
                        project="",
                        department="",
                        counterparty_id="client-1",
                        tx_date="2026-08-01",
                        description="consulting service revenue accounts receivable",
                        amount=5500000,
                        debit_account_code="1100",
                        credit_account_code="4100",
                        account_codes=["1100", "4100"],
                    ),
                    raw(
                        "b",
                        project="",
                        department="",
                        counterparty_id="client-1",
                        tx_date="2026-08-05",
                        description="accounts receivable collection payment",
                        amount=5500000,
                        debit_account_code="1000",
                        credit_account_code="1100",
                        account_codes=["1000", "1100"],
                    ),
                ],
                include_external_context=False,
            )
        )
        candidate = result["candidates"][0]
        self.assertGreater(candidate["relationship_score"], 0.45)
        self.assertGreater(candidate["evidence_coverage"], 0.5)
        self.assertIn("REVENUE_COLLECTION", candidate["relationship_types"])
        signals = {signal["type"]: signal for signal in candidate["signals"]}
        self.assertFalse(signals["same_project"]["available"])
        self.assertFalse(signals["same_department"]["available"])

    def test_same_project_unrelated_transactions_do_not_overboost_relationship(self) -> None:
        engine = AssemblyRecommendationEngine(cluster_threshold=0.5)
        result = asyncio.run(
            engine.recommend(
                [
                    raw("a", project="IFRS18", department="Dev", description="server hosting fee", debit_account_code="5300", credit_account_code="2100"),
                    raw("b", project="IFRS18", department="Dev", description="travel meal expense", debit_account_code="6200", credit_account_code="1000", counterparty_id="card"),
                ],
                include_external_context=False,
            )
        )
        self.assertLess(result["candidates"][0]["relationship_score"], 0.5)

    def test_singletons_preserve_nearest_below_threshold_relationship(self) -> None:
        engine = AssemblyRecommendationEngine(cluster_threshold=0.9)
        result = asyncio.run(
            engine.recommend(
                [
                    raw("a", project="", department="", description="SaaS subscription prepayment", amount=1000, account_codes=["1500"]),
                    raw("b", project="", department="", description="SaaS subscription expense recognition", amount=1000, account_codes=["1500", "6200"]),
                ],
                include_external_context=False,
            )
        )
        self.assertEqual(len(result["candidates"]), 2)
        nearest = [item for candidate in result["candidates"] for item in candidate["nearest_relationships"]]
        self.assertTrue(nearest)
        self.assertGreater(nearest[0]["relationship_score"], 0.0)
        self.assertTrue(nearest[0]["below_grouping_threshold"])

    def test_identity_field_difference_is_not_integrity_warning(self) -> None:
        engine = AssemblyRecommendationEngine()
        result = asyncio.run(
            engine.recommend(
                [
                    {**raw("a"), "created_by_name": "user-label", "created_by_display": {"name": "Profile Name"}},
                    {**raw("b"), "created_by_name": "different-label", "created_by_display": {"name": "Another Profile"}},
                ],
                include_external_context=False,
            )
        )
        warning_text = " ".join(result["candidates"][0]["warnings"])
        self.assertNotIn("created_by", warning_text.lower())


if __name__ == "__main__":
    unittest.main()
