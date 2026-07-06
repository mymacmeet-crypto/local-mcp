import json
import unittest

from local_mcp.search.searxng import SearchResult
from local_mcp.tools import web
from local_mcp.web.fetcher import FetchResult


class WebFetchToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._fetch_static = web.fetcher.fetch_static
        self._fetch_browser = web.fetcher.fetch_browser
        self._search = web.searxng.search

    async def asyncTearDown(self):
        web.fetcher.fetch_static = self._fetch_static
        web.fetcher.fetch_browser = self._fetch_browser
        web.searxng.search = self._search

    async def test_web_fetch_static_markdown_with_metadata_and_links(self):
        async def fake_static(url: str, *, accept: str | None = None) -> FetchResult:
            return FetchResult(
                html="""
                <html>
                  <head><title>Example Page</title></head>
                  <body>
                    <main>
                      <h1>Example Page</h1>
                      <p>Hello <a href="/docs">docs</a>.</p>
                    </main>
                  </body>
                </html>
                """,
                final_url="https://example.com/start",
                status=200,
            )

        web.fetcher.fetch_static = fake_static

        result = await web.web_fetch(
            "https://example.com/start",
            render="static",
            include_links=True,
        )

        self.assertIn("Fetch metadata:", result)
        self.assertIn("- Render method: httpx", result)
        self.assertIn("# Example Page", result)
        self.assertIn("[docs](https://example.com/docs)", result)
        self.assertIn("Links:", result)

    async def test_web_fetch_auto_uses_browser_when_browser_content_is_better(self):
        async def fake_static(url: str, *, accept: str | None = None) -> FetchResult:
            return FetchResult(
                html="<html><body><div id='root'></div></body></html>",
                final_url="https://example.com/app",
                status=200,
            )

        async def fake_browser(url: str) -> FetchResult:
            return FetchResult(
                html="<html><body><main><p>Rendered app content</p></main></body></html>",
                final_url=url,
                status=200,
                markdown="Rendered app content " * 20,
            )

        web.fetcher.fetch_static = fake_static
        web.fetcher.fetch_browser = fake_browser

        result = await web.web_fetch(
            "https://example.com/app",
            render="auto",
            include_metadata=False,
        )

        self.assertIn("Rendered app content", result)
        self.assertNotIn("Fetch metadata:", result)

    async def test_web_fetch_json_includes_structured_scrape_data(self):
        async def fake_static(url: str, *, accept: str | None = None) -> FetchResult:
            return FetchResult(
                html="""
                <html>
                  <head>
                    <title>Catalog</title>
                    <meta name="description" content="Catalog page">
                  </head>
                  <body>
                    <main>
                      <article class="item">
                        <h1>Item</h1>
                        <a href="/item">Open item</a>
                        <img src="/item.png" alt="Item image">
                      </article>
                    </main>
                  </body>
                </html>
                """,
                final_url="https://example.com/catalog",
                status=200,
            )

        web.fetcher.fetch_static = fake_static

        payload = json.loads(
            await web.web_fetch(
                "https://example.com/catalog",
                render="static",
                output_format="json",
                selector=".item",
                include_metadata=False,
            )
        )

        self.assertEqual(payload["render_method"], "httpx")
        self.assertEqual(payload["metadata"]["title"], "Catalog")
        self.assertEqual(payload["selector"], ".item")
        self.assertIn("Item", payload["content"])
        self.assertEqual(payload["links"][0]["url"], "https://example.com/item")
        self.assertEqual(payload["images"][0]["url"], "https://example.com/item.png")

    async def test_web_summarize_summarizes_explicit_urls(self):
        async def fake_static(url: str, *, accept: str | None = None) -> FetchResult:
            title = "Alpha Article" if url.endswith("/alpha") else "Beta Article"
            topic = "Alpha" if url.endswith("/alpha") else "Beta"
            return FetchResult(
                html=f"""
                <html>
                  <head><title>{title}</title></head>
                  <body>
                    <main>
                      <h1>{title}</h1>
                      <p>{topic} explains local search orchestration for multiple source pages.</p>
                      <p>{topic} crawls each selected URL and returns concise summaries instead of full page text.</p>
                      <p>The implementation keeps source URLs visible so users can inspect the original material.</p>
                    </main>
                  </body>
                </html>
                """,
                final_url=url,
                status=200,
            )

        web.fetcher.fetch_static = fake_static

        result = await web.web_summarize(
            urls="- [Alpha](https://example.com/alpha)\nhttps://example.com/beta",
            render="static",
            limit=2,
            summary_sentences=2,
        )

        self.assertIn("Web summary:", result)
        self.assertIn("[Alpha Article](https://example.com/alpha)", result)
        self.assertIn("[Beta Article](https://example.com/beta)", result)
        self.assertNotIn("<main>", result)

    async def test_web_summarize_searches_then_summarizes_results(self):
        async def fake_search(*args, **kwargs):
            return (
                "http://searx.local/",
                [
                    SearchResult(
                        title="Search Summary Result",
                        url="https://example.com/search-result",
                        content="Search result snippet about summary generation.",
                        engines=["example"],
                        score=1.0,
                    )
                ],
                [],
                [],
            )

        async def fake_static(url: str, *, accept: str | None = None) -> FetchResult:
            return FetchResult(
                html="""
                <html>
                  <head><title>Search Summary Result</title></head>
                  <body>
                    <article>
                      <h1>Search Summary Result</h1>
                      <p>Summary generation fetches the search result URL and extracts the readable article body.</p>
                      <p>The returned response is intentionally concise and keeps citations attached to each source.</p>
                    </article>
                  </body>
                </html>
                """,
                final_url=url,
                status=200,
            )

        web.searxng.search = fake_search
        web.fetcher.fetch_static = fake_static

        result = await web.web_summarize(
            query="summary generation",
            render="static",
            limit=1,
        )

        self.assertIn("[Search Summary Result](https://example.com/search-result)", result)
        self.assertIn("Summary generation fetches the search result URL", result)


if __name__ == "__main__":
    unittest.main()
