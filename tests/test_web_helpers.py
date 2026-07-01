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


if __name__ == "__main__":
    unittest.main()
