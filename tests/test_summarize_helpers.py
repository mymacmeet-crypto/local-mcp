import unittest

from local_mcp.shared import summarize


class SummarizeHelperTests(unittest.TestCase):
    SAMPLE = (
        "The Model Context Protocol lets clients connect to tools over a "
        "standard interface. MCP servers expose tools such as web search and "
        "web fetch. A web search returns candidate sources for a question. "
        "Fetching a page returns the full content used as evidence. Short "
        "snippets alone are usually not enough to answer accurately."
    )

    def test_summarize_text_is_extractive_and_bounded(self):
        summary = summarize.summarize_text(self.SAMPLE, query="MCP tools web search", max_chars=200)

        self.assertTrue(summary)
        self.assertLessEqual(len(summary), 203)  # allow the trailing ellipsis
        # Extractive: the summary text comes from the source sentences.
        self.assertIn("MCP", summary + self.SAMPLE)

    def test_summarize_text_handles_empty_input(self):
        self.assertEqual(summarize.summarize_text(""), "")
        self.assertEqual(summarize.extract_key_points(""), [])

    def test_extract_key_points_returns_distinct_bounded_points(self):
        points = summarize.extract_key_points(self.SAMPLE, query="evidence fetch", max_points=3)

        self.assertGreater(len(points), 0)
        self.assertLessEqual(len(points), 3)
        self.assertEqual(len(points), len({point.lower() for point in points}))

    def test_keywords_drops_short_and_stopwords(self):
        words = summarize.keywords("The quick brown fox with a plan")

        self.assertIn("quick", words)
        self.assertIn("brown", words)
        self.assertNotIn("with", words)  # stopword
        self.assertNotIn("a", words)  # too short


if __name__ == "__main__":
    unittest.main()
