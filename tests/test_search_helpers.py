import unittest
from unittest.mock import patch

from local_mcp.search import searxng
from local_mcp.search.searxng import SearchResult
from local_mcp.tools import search as search_tool
from local_mcp.tools import simple, web
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


class WebSearchFollowUpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._search_tool_search = search_tool.searxng.search
        self._web_search = web.searxng.search
        self._fetch_static = web.fetcher.fetch_static
        self._fetch_browser = web.fetcher.fetch_browser

    async def asyncTearDown(self):
        search_tool.searxng.search = self._search_tool_search
        web.searxng.search = self._web_search
        web.fetcher.fetch_static = self._fetch_static
        web.fetcher.fetch_browser = self._fetch_browser

    async def test_web_search_can_summarize_results_after_search(self):
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
                      <p>Fetched article content explains how follow-up summarization reads the page after search and creates richer evidence for a report.</p>
                      <p>The fetched page includes enough detail for the summary builder to produce useful source notes instead of relying on snippets alone.</p>
                    </main>
                  </body>
                </html>
                """,
                final_url=url,
                status=200,
            )

        search_tool.searxng.search = fake_search
        web.fetcher.fetch_static = fake_static

        with patch.dict("os.environ", {"LOCAL_MCP_WEB_SEARCH_FOLLOW_UP": "summarize"}, clear=False):
            result = await search_tool.web_search("follow up test", limit=1)

        self.assertIn("Results:", result)
        self.assertIn("Follow-up web_summarize result:", result)
        self.assertIn("Fetched article content explains", result)

    async def test_simple_search_web_searches_and_summarizes(self):
        async def fake_search(*args, **kwargs):
            return (
                "http://searx.local/",
                [
                    SearchResult(
                        title="Simple Search Result",
                        url="https://example.com/simple",
                        content="Snippet about automatic summarization.",
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
                  <head><title>Simple Search Result</title></head>
                  <body>
                    <article>
                      <h1>Simple Search Result</h1>
                      <p>Simple search now fetches pages after searching so weaker models receive source-backed summaries for report writing.</p>
                      <p>This avoids creating files from only short search result snippets when the user expects a fuller answer.</p>
                    </article>
                  </body>
                </html>
                """,
                final_url=url,
                status=200,
            )

        web.searxng.search = fake_search
        web.fetcher.fetch_static = fake_static

        result = await simple.search_web("simple follow up", limit=1)

        self.assertIn("Web summary:", result)
        self.assertIn("Simple search now fetches pages", result)


if __name__ == "__main__":
    unittest.main()
