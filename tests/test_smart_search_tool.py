import json
import unittest

from local_mcp.llm.client import LLMError
from local_mcp.search.searxng import SearchResult
from local_mcp.shared.errors import ToolError
from local_mcp.tools import smart_search
from local_mcp.web.fetcher import FetchResult


def _result(index: int) -> SearchResult:
    return SearchResult(
        title=f"Title {index}",
        url=f"https://example.com/{index}",
        content=f"Snippet {index}",
        engines=["duckduckgo"],
    )


class SmartSearchToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._orig = {
            "is_configured": smart_search.llm.is_configured,
            "generate_text": smart_search.llm.generate_text,
            "search": smart_search.searxng.search,
            "fetch_auto": smart_search.content.fetch_auto,
            "page_markdown": smart_search.content.page_markdown,
        }
        smart_search.llm.is_configured = lambda: True

        async def fake_search(query, *, limit, time_range=None, **kwargs):
            return ("http://searxng", [_result(i) for i in range(5)], [], [])

        async def fake_fetch_auto(target):
            return FetchResult(html="", final_url=target, status=200, markdown=f"body of {target}")

        smart_search.searxng.search = fake_search
        smart_search.content.fetch_auto = fake_fetch_auto
        smart_search.content.page_markdown = lambda page: page.markdown or ""

    async def asyncTearDown(self):
        smart_search.llm.is_configured = self._orig["is_configured"]
        smart_search.llm.generate_text = self._orig["generate_text"]
        smart_search.searxng.search = self._orig["search"]
        smart_search.content.fetch_auto = self._orig["fetch_auto"]
        smart_search.content.page_markdown = self._orig["page_markdown"]

    async def test_happy_path_ranks_crawls_and_summarizes(self):
        calls = []

        async def fake_generate(prompt, *, model=None, system=None, temperature=0.2, response_mime_type=None, **kwargs):
            calls.append({"system": system, "mime": response_mime_type})
            if response_mime_type == "application/json":
                # LLM selects results 2 and 0 (best first).
                return json.dumps({"indexes": [2, 0]})
            return "Synthesized answer citing [1] and [2]."

        smart_search.llm.generate_text = fake_generate

        output = await smart_search.smart_search("what is x?", max_sources=2)

        # Summary text is returned, followed by the Sources list.
        self.assertIn("Synthesized answer citing [1] and [2].", output)
        self.assertIn("Sources:", output)
        # LLM-chosen order (2 then 0) is preserved in the crawled sources.
        self.assertIn("[1] https://example.com/2", output)
        self.assertIn("[2] https://example.com/0", output)
        # Exactly two LLM calls: one ranking (json), one summary (with system prompt).
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["mime"], "application/json")
        self.assertIsNotNone(calls[1]["system"])

    async def test_ranking_failure_falls_back_to_search_order(self):
        async def fake_generate(prompt, *, model=None, system=None, temperature=0.2, response_mime_type=None, **kwargs):
            if response_mime_type == "application/json":
                raise LLMError("ranking failed")
            return "Fallback summary."

        smart_search.llm.generate_text = fake_generate

        output = await smart_search.smart_search("topic", max_sources=2)

        # Falls back to the first two search results in order.
        self.assertIn("[1] https://example.com/0", output)
        self.assertIn("[2] https://example.com/1", output)

    async def test_not_configured_raises_tool_error(self):
        smart_search.llm.is_configured = lambda: False
        with self.assertRaises(ToolError):
            await smart_search.smart_search("anything")

    async def test_no_results_raises_tool_error(self):
        async def empty_search(query, *, limit, time_range=None, **kwargs):
            return ("http://searxng", [], [], [])

        smart_search.searxng.search = empty_search
        with self.assertRaises(ToolError):
            await smart_search.smart_search("anything")

    def test_parse_indexes_filters_out_of_range_and_dupes(self):
        parsed = smart_search._parse_indexes('{"indexes": [1, 1, 9, 2, -1]}', count=3)
        self.assertEqual(parsed, [1, 2])

    def test_parse_indexes_recovers_from_plain_text(self):
        parsed = smart_search._parse_indexes("Use 0 and 2 please", count=3)
        self.assertEqual(parsed, [0, 2])


if __name__ == "__main__":
    unittest.main()
