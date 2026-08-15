from __future__ import annotations

import asyncio
import unittest

from cajas_mcp.adapters.external_context import ExternalSearchResult
from cajas_mcp.services import AssemblyRecommendationEngine


class FakeExternalProvider:
    async def search(self, query: str, *, limit: int = 5) -> list[ExternalSearchResult]:
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
        "debit_account_code": "5300",
        "credit_account_code": "2100",
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


if __name__ == "__main__":
    unittest.main()

