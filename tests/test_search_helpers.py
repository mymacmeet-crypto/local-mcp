import json
import unittest
from unittest.mock import patch

from local_mcp.search import searxng
from local_mcp.search.searxng import SearchResult
from local_mcp.tools import search as search_tool
from local_mcp.tools import web
from local_mcp.web.fetcher import FetchResult


class SearchHelperTests(unittest.TestCase):
    def test_parse_results_cleans_deduplicates_and_limits(self):
        data = {
            "results": [
                {
                    "url": "https://example.com/a",
                    "title": " Example A ",
                    "content": "One   two",
                    "engines": ["duckduckgo"],
                    "publishedDate": "2026-01-01",
                    "score": "2.5",
                },
                {"url": "https://example.com/a", "title": "Duplicate"},
                {"url": "https://example.com/b", "title": "Example B"},
            ]
        }

        results = searxng._parse_results(data, limit=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Example A")
        self.assertEqual(results[0].content, "One two")
        self.assertEqual(results[0].engines, ["duckduckgo"])
        self.assertEqual(results[0].score, 2.5)

    def test_relevance_scores_prefer_query_overlap_and_engine_score(self):
        results = [
            SearchResult(
                title="Quarterfinal schedule and kickoff times",
                url="https://example.com/alpha",
                content="Full quarterfinal schedule with kickoff times for the tournament.",
                engines=["e"],
                score=10.0,
            ),
            SearchResult(
                title="Unrelated cooking blog",
                url="https://example.com/beta",
                content="A recipe for banana bread.",
                engines=["e"],
                score=1.0,
            ),
        ]

        scores = search_tool._relevance_scores("quarterfinal schedule kickoff", results)

        self.assertEqual(len(scores), 2)
        self.assertGreater(scores[0], scores[1])
        self.assertTrue(all(0.0 <= score <= 1.0 for score in scores))


class WebSearchFollowUpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._search_tool_search = search_tool.searxng.search
        self._fetch_static = web.fetcher.fetch_static
        self._fetch_browser = web.fetcher.fetch_browser

    async def asyncTearDown(self):
        search_tool.searxng.search = self._search_tool_search
        web.fetcher.fetch_static = self._fetch_static
        web.fetcher.fetch_browser = self._fetch_browser

    async def test_web_search_prefetches_top_result_when_follow_up_enabled(self):
        async def fake_search(*args, **kwargs):
            return (
                "http://searx.local/",
                [
                    SearchResult(
                        title="Follow Up Result",
                        url="https://example.com/follow-up",
                        content="Snippet about richer report evidence.",
                        engines=["example"],
                    )
                ],
                [],
                [],
            )

        async def fake_static(url: str, *, accept: str | None = None) -> FetchResult:
            return FetchResult(
                html="""
                <html>
                  <head><title>Follow Up Result</title></head>
                  <body>
                    <main>
                      <h1>Follow Up Result</h1>
                      <p>Fetched article content explains how follow-up fetching reads the page after search and creates richer evidence for a report.</p>
                      <p>The fetched page includes enough detail to produce useful source notes instead of relying on snippets alone.</p>
                    </main>
                  </body>
                </html>
                """,
                final_url=url,
                status=200,
            )

        search_tool.searxng.search = fake_search
        web.fetcher.fetch_static = fake_static

        with patch.dict("os.environ", {"LOCAL_MCP_WEB_SEARCH_FOLLOW_UP": "fetch_first"}, clear=False):
            payload = json.loads(await search_tool.web_search("follow up test", limit=1))

        self.assertEqual(payload["stage"], "discovery")
        self.assertFalse(payload["requires_fetch"])
        self.assertEqual(len(payload["prefetched_sources"]), 1)
        prefetched = payload["prefetched_sources"][0]
        self.assertEqual(prefetched["tool"], "web_fetch")
        self.assertIn("Fetched article content explains", prefetched["content"])
        self.assertEqual(payload["results"][0]["url"], "https://example.com/follow-up")

    async def test_web_search_returns_discovery_envelope_without_follow_up(self):
        async def fake_search(*args, **kwargs):
            return (
                "http://searx.local/",
                [
                    SearchResult(
                        title="Alpha Result",
                        url="https://example.com/alpha",
                        content="Alpha explains the quarterfinal schedule and kickoff times for the tournament.",
                        engines=["example"],
                        score=1.0,
                    ),
                    SearchResult(
                        title="Beta Result",
                        url="https://example.com/beta",
                        content="Beta covers live-streaming and broadcast details for the same matches.",
                        engines=["example"],
                        score=0.5,
                    ),
                ],
                [],
                [],
            )

        search_tool.searxng.search = fake_search

        with patch.dict("os.environ", {"LOCAL_MCP_WEB_SEARCH_FOLLOW_UP": "none"}, clear=False):
            payload = json.loads(await search_tool.web_search("quarterfinal schedule", limit=2))

        self.assertEqual(payload["tool"], "web_search")
        self.assertEqual(payload["stage"], "discovery")
        self.assertTrue(payload["requires_fetch"])
        self.assertEqual(payload["result_count"], 2)
        self.assertNotIn("prefetched_sources", payload)

        urls = [result["url"] for result in payload["results"]]
        self.assertEqual(urls, ["https://example.com/alpha", "https://example.com/beta"])
        self.assertIn("relevance_score", payload["results"][0])
        self.assertIn("https://example.com/alpha", payload["recommended_urls"])

        # The old plain "Overall Summary" answer-shaped output is gone.
        self.assertNotIn("Overall Summary", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
