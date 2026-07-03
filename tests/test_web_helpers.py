import unittest

from local_mcp.web import html, sitemap


class WebHelperTests(unittest.TestCase):
    def test_extract_links_resolves_filters_and_deduplicates(self):
        source = """
        <html>
          <a href="/about#team">About</a>
          <a href="/about">About duplicate</a>
          <a href="https://other.example/page">External</a>
          <link href="/feed.xml">
        </html>
        """

        self.assertEqual(
            html.extract_links(source, "https://example.com/blog/", same_domain=True),
            ["https://example.com/about", "https://example.com/feed.xml"],
        )

    def test_parse_sitemap_splits_child_sitemaps_and_urls(self):
        xml = """
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/page</loc></url>
          <url><loc>https://example.com/section.xml</loc></url>
        </urlset>
        """

        child_sitemaps, page_urls = sitemap.parse_sitemap(xml, "https://example.com/sitemap.xml")

        self.assertEqual(child_sitemaps, ["https://example.com/section.xml"])
        self.assertEqual(page_urls, ["https://example.com/page"])

    def test_scrape_helpers_support_selectors_metadata_links_and_images(self):
        source = """
        <html lang="en">
          <head>
            <title>Fallback title</title>
            <meta name="description" content="A useful test page">
            <link rel="canonical" href="/canonical">
          </head>
          <body>
            <main>
              <section class="product">
                <h1>Widget</h1>
                <p>Buy the <a href="/buy">starter kit</a>.</p>
                <img src="/widget.png" alt="Widget photo" width="640" height="480">
              </section>
              <aside>Navigation noise</aside>
            </main>
          </body>
        </html>
        """

        metadata = html.extract_metadata(source, "https://example.com/products/widget")
        self.assertEqual(metadata["title"], "Fallback title")
        self.assertEqual(metadata["description"], "A useful test page")
        self.assertEqual(metadata["canonical_url"], "https://example.com/canonical")
        self.assertEqual(metadata["language"], "en")
        self.assertEqual(metadata["h1"], "Widget")

        markdown = html.html_to_markdown(source, "https://example.com/products/widget", selector=".product")
        self.assertIn("[starter kit](https://example.com/buy)", markdown)
        self.assertNotIn("Navigation noise", markdown)

        text = html.html_to_text(source, selector=".product")
        self.assertIn("Widget", text)
        self.assertNotIn("Navigation noise", text)

        self.assertEqual(
            html.extract_link_details(source, "https://example.com/products/widget", selector=".product"),
            [{"url": "https://example.com/buy", "text": "starter kit"}],
        )
        self.assertEqual(
            html.extract_images(source, "https://example.com/products/widget", selector=".product"),
            [
                {
                    "url": "https://example.com/widget.png",
                    "alt": "Widget photo",
                    "title": "",
                    "width": "640",
                    "height": "480",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
