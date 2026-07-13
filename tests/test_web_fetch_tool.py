import json
import unittest

from local_mcp.tools import web
from local_mcp.web.fetcher import FetchResult

ENVELOPE_KEYS = {
    "stage",
    "url",
    "requires_analysis",
    "workflow",
    "agent_guidance",
    "next_action",
    "content",
}


class WebFetchToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._fetch_static = web.fetcher.fetch_static
        self._fetch_browser = web.fetcher.fetch_browser

    async def asyncTearDown(self):
        web.fetcher.fetch_static = self._fetch_static
        web.fetcher.fetch_browser = self._fetch_browser

    async def test_web_fetch_returns_minimal_evidence_envelope(self):
        async def fake_static(url: str, *, accept: str | None = None) -> FetchResult:
            return FetchResult(
                html="""
                <html>
                  <head><title>Example Page</title></head>
                  <body>
                    <main>
                      <h1>Example Page</h1>
                      <p>Hello there, this is a detailed example paragraph about documentation.</p>
                      <p>It links to the <a href="/docs">docs</a> for further reading and evidence.</p>
                    </main>
                  </body>
                </html>
                """,
                final_url="https://example.com/start",
                status=200,
            )

        web.fetcher.fetch_static = fake_static

        payload = json.loads(await web.web_fetch("https://example.com/start"))

        # Only the seven minimal fields, nothing extra.
        self.assertEqual(set(payload), ENVELOPE_KEYS)
        self.assertEqual(payload["stage"], "evidence")
        self.assertEqual(payload["url"], "https://example.com/start")
        self.assertTrue(payload["requires_analysis"])
        self.assertIn("do not paste", payload["agent_guidance"].lower())
        # Content is Markdown extracted from the main region.
        self.assertIn("# Example Page", payload["content"])
        self.assertIn("[docs](https://example.com/docs)", payload["content"])

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

        payload = json.loads(await web.web_fetch("https://example.com/app"))

        self.assertEqual(set(payload), ENVELOPE_KEYS)
        self.assertIn("Rendered app content", payload["content"])

    async def test_web_fetch_truncates_content_to_max_chars(self):
        async def fake_static(url: str, *, accept: str | None = None) -> FetchResult:
            body = "<p>" + ("word " * 500) + "</p>"
            return FetchResult(
                html=f"<html><body><main>{body}</main></body></html>",
                final_url="https://example.com/long",
                status=200,
            )

        web.fetcher.fetch_static = fake_static

        payload = json.loads(await web.web_fetch("https://example.com/long", max_chars=50))

        self.assertLessEqual(len(payload["content"]), 50)


if __name__ == "__main__":
    unittest.main()
