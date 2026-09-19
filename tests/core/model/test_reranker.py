import asyncio
import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

import httpx

from adapter.model.reranker import MemoryReranker


class RerankerTests(IsolatedAsyncioTestCase):
    def candidates(self):
        return [SimpleNamespace(memory=SimpleNamespace(payload=SimpleNamespace(content=text)), score=score)
                for text, score in (("first", 0.9), ("second", 0.7))]

    def client(self, handler):
        client = MemoryReranker(api_key="test", base_url="https://example.com/v1",
            model="test-rerank-model", transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.close)
        return client

    async def test_reorders_by_index_without_overwriting_vector_scores(self):
        def handler(request):
            self.assertEqual(str(request.url), "https://example.com/v1/rerank")
            body = json.loads(request.content)
            self.assertEqual(body["documents"], ["first", "second"])
            self.assertEqual(body["top_n"], 2)
            return httpx.Response(200, json={"results": [
                {"index": 0, "relevance_score": 0.1}, {"index": 1, "relevance_score": 0.99}]})
        candidates = self.candidates()
        result = await self.client(handler).rerank("query", candidates)
        self.assertIs(result[0], candidates[1])
        self.assertEqual([c.score for c in result], [0.7, 0.9])

    async def test_invalid_results_fall_back_without_losing_candidates(self):
        for results in ([], [{"index": 0, "relevance_score": 1}] * 2,
            [{"index": 2, "relevance_score": 1}, {"index": 0, "relevance_score": 1}],
            [{"index": True, "relevance_score": 1}, {"index": 0, "relevance_score": 1}]):
            with self.subTest(results=results):
                client = self.client(lambda request: httpx.Response(200, json={"results": results}))
                candidates = self.candidates()
                self.assertEqual(await client.rerank("query", candidates), candidates)

    async def test_http_failure_and_timeout_fall_back(self):
        def timeout(request):
            raise httpx.ReadTimeout("timeout")
        for handler in (timeout, lambda request: httpx.Response(503)):
            candidates = self.candidates()
            self.assertEqual(await self.client(handler).rerank("query", candidates), candidates)

    async def test_small_batches_do_not_call_api(self):
        def handler(request):
            self.fail("unexpected request")
        client = self.client(handler)
        self.assertEqual(await client.rerank("query", []), [])
        single = self.candidates()[:1]
        self.assertEqual(await client.rerank("query", single), single)

    async def test_cancellation_is_not_swallowed(self):
        def handler(request):
            raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.client(handler).rerank("query", self.candidates())
