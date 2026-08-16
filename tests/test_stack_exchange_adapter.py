from __future__ import annotations

import asyncio
import unittest

import httpx

from cajas_mcp.adapters.stack_exchange import StackExchangeProvider


class StackExchangeAdapterTests(unittest.TestCase):
    def test_search_enriches_question_content_answers_and_url(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/search/excerpts"):
                return httpx.Response(
                    200,
                    json={
                        "quota_remaining": 99,
                        "items": [
                            {
                                "question_id": 123,
                                "title": "Cloud SaaS implementation",
                                "excerpt": "cloud saas implementation",
                                "tags": ["cloud", "saas"],
                                "score": 4,
                            }
                        ],
                    },
                )
            if path.endswith("/questions/123"):
                return httpx.Response(
                    200,
                    json={
                        "quota_remaining": 98,
                        "items": [
                            {
                                "question_id": 123,
                                "title": "Cloud SaaS implementation",
                                "link": "https://stackoverflow.com/questions/123/cloud-saas-implementation",
                                "body": "<p>Cloud implementation and deployment operations are part of this setup.</p>",
                                "accepted_answer_id": 456,
                                "score": 4,
                                "tags": ["cloud", "saas"],
                                "content_license": "CC BY-SA 4.0",
                            }
                        ],
                    },
                )
            if path.endswith("/questions/123/answers"):
                return httpx.Response(
                    200,
                    json={
                        "quota_remaining": 97,
                        "items": [
                            {
                                "question_id": 123,
                                "answer_id": 456,
                                "body": "<p>The subscription setup is usually handled with deployment workflow.</p>",
                                "is_accepted": True,
                                "score": 8,
                            }
                        ],
                    },
                )
            return httpx.Response(404, json={})

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.stackexchange.com/2.3",
        )
        provider = StackExchangeProvider(http_client=client, max_evidence_items=2, max_answers_per_question=1)
        results = asyncio.run(provider.search("cloud infrastructure saas", limit=5))
        asyncio.run(provider.aclose())

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://stackoverflow.com/questions/123/cloud-saas-implementation")
        self.assertTrue(results[0].content_reviewed)
        self.assertIn("deployment operations", results[0].content_summary or "")
        self.assertIn("subscription setup", results[0].content_summary or "")
        self.assertEqual(results[0].answer_score, 8)
        self.assertEqual(results[0].content_license, "CC BY-SA 4.0")


if __name__ == "__main__":
    unittest.main()
