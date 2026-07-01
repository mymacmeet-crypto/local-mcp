import unittest

from local_mcp.shared import urls


class UrlHelperTests(unittest.TestCase):
    def test_normalize_url_adds_https(self):
        self.assertEqual(urls.normalize_url("example.com/path"), "https://example.com/path")

    def test_normalize_discovered_url_resolves_and_strips_fragment(self):
        self.assertEqual(
            urls.normalize_discovered_url("../about#team", "https://example.com/blog/post"),
            "https://example.com/about",
        )

    def test_same_path_prefix(self):
        self.assertTrue(urls.same_path_prefix("https://example.com/blog/post", "https://example.com/blog"))
        self.assertFalse(urls.same_path_prefix("https://example.com/docs", "https://example.com/blog"))


if __name__ == "__main__":
    unittest.main()
