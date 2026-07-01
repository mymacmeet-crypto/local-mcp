import unittest

from local_mcp.search import searxng


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


if __name__ == "__main__":
    unittest.main()
