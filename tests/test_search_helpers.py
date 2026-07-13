import json
import unittest

from local_mcp.search import searxng
from local_mcp.search.searxng import SearchResult
from local_mcp.tools import search as search_tool

ENVELOPE_KEYS = {
    "stage",
    "query",
    "requires_fetch",
    "workflow",
    "agent_guidance",
    "next_action",
    "urls",
}


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


class WebSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._search = search_tool.searxng.search

    async def asyncTearDown(self):
        search_tool.searxng.search = self._search

    async def test_web_search_returns_minimal_url_envelope(self):
        async def fake_search(*args, **kwargs):
            return (
                "http://searx.local/",
                [
                    SearchResult(
                        title="Alpha Result",
                        url="https://example.com/alpha",
                        content="Alpha snippet.",
                        engines=["example"],
                        score=1.0,
                    ),
                    SearchResult(
                        title="Beta Result",
                        url="https://example.com/beta",
                        content="Beta snippet.",
                        engines=["example"],
                        score=0.5,
                    ),
                ],
                ["an instant answer that must not surface"],
                ["a suggestion that must not surface"],
            )

        search_tool.searxng.search = fake_search

        payload = json.loads(await search_tool.web_search("quarterfinal schedule", limit=2))

        # Only the seven minimal fields, nothing extra.
        self.assertEqual(set(payload), ENVELOPE_KEYS)
        self.assertEqual(payload["stage"], "discovery")
        self.assertEqual(payload["query"], "quarterfinal schedule")
        self.assertTrue(payload["requires_fetch"])
        # URLs are returned in SearXNG order (no relevance re-ranking).
        self.assertEqual(
            payload["urls"],
            ["https://example.com/alpha", "https://example.com/beta"],
        )

    async def test_web_search_marks_empty_results(self):
        async def fake_search(*args, **kwargs):
            return ("http://searx.local/", [], [], [])

        search_tool.searxng.search = fake_search

        payload = json.loads(await search_tool.web_search("nothing matches this"))

        self.assertEqual(set(payload), ENVELOPE_KEYS)
        self.assertFalse(payload["requires_fetch"])
        self.assertEqual(payload["urls"], [])


if __name__ == "__main__":
    unittest.main()
