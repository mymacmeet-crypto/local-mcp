import json
import unittest

from local_mcp.tools import web
from local_mcp.web.fetcher import FetchResult


class WebFetchToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._fetch_static = web.fetcher.fetch_static
        self._fetch_browser = web.fetcher.fetch_browser

    async def asyncTearDown(self):
        web.fetcher.fetch_static = self._fetch_static
        web.fetcher.fetch_browser = self._fetch_browser

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


if __name__ == "__main__":
    unittest.main()
