import json
import unittest

from local_mcp.search.searxng import SearchResult
from local_mcp.shared.errors import ToolError
from local_mcp.tools import deep_research
from local_mcp.web.fetcher import FetchResult


def _result(index: int) -> SearchResult:
    return SearchResult(
        title=f"Title {index}",
        url=f"https://example.com/{index}",
        content=f"Snippet {index}",
        engines=["duckduckgo"],
    )


def _classify(prompt: str, system: str | None, mime: str | None) -> str:
    """Return a canned reply for whichever pipeline stage the call belongs to."""
    if mime == "application/json":
        if "subquestions" in prompt:
            return json.dumps({"subquestions": ["sub a", "sub b"], "outline": ["Intro", "Findings"]})
        if "Rank ALL" in prompt:
            return json.dumps({"indexes": [1, 0, 2, 3, 4]})
        # reflection: stop after the first round so tests are deterministic.
        return json.dumps({"done": True, "gaps": "", "queries": []})
    if system and "extract only the facts" in system:
        return "- [1] a relevant fact."
    if system and "research analyst" in system:
        return "# Report\n\nBody citing [1] and [2].\n\n## Limitations\n\nThin."
    if system and "fact-checking auditor" in system:
        return "All claims are supported by the cited sources."
    return "unexpected"


class DeepResearchToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._orig = {
            "is_configured": deep_research.llm.is_configured,
            "generate_text": deep_research.llm.generate_text,
            "search": deep_research.searxng.search,
            "fetch_auto": deep_research.content.fetch_auto,
            "page_markdown": deep_research.content.page_markdown,
        }
        deep_research.llm.is_configured = lambda: True

        async def fake_search(query, *, limit, time_range=None, **kwargs):
            return ("http://searxng", [_result(i) for i in range(5)], [], [])

        async def fake_fetch_auto(target):
            return FetchResult(html="", final_url=target, status=200, markdown=f"body of {target}")

        deep_research.searxng.search = fake_search
        deep_research.content.fetch_auto = fake_fetch_auto
        deep_research.content.page_markdown = lambda page: page.markdown or ""

    async def asyncTearDown(self):
        deep_research.llm.is_configured = self._orig["is_configured"]
        deep_research.llm.generate_text = self._orig["generate_text"]
        deep_research.searxng.search = self._orig["search"]
        deep_research.content.fetch_auto = self._orig["fetch_auto"]
        deep_research.content.page_markdown = self._orig["page_markdown"]

    async def test_happy_path_plans_crawls_synthesizes_and_verifies(self):
        systems: list[str | None] = []

        async def fake_generate(prompt, *, model=None, system=None, temperature=0.2, response_mime_type=None, **kwargs):
            systems.append(system)
            return _classify(prompt, system, response_mime_type)

        deep_research.llm.generate_text = fake_generate

        output = await deep_research.deep_research("what is x?", breadth=2, max_iterations=1, verify=True)

        self.assertIn("# Report", output)
        self.assertIn("## Verification", output)
        self.assertIn("All claims are supported", output)
        self.assertIn("## Sources", output)
        self.assertIn("[1] https://example.com/1", output)  # LLM-ranked order (1 before 0)
        self.assertIn("[2] https://example.com/0", output)
        # A synthesis and a verification call both ran.
        self.assertTrue(any(s and "research analyst" in s for s in systems))
        self.assertTrue(any(s and "fact-checking auditor" in s for s in systems))

    async def test_verify_false_skips_verification_section(self):
        async def fake_generate(prompt, *, model=None, system=None, temperature=0.2, response_mime_type=None, **kwargs):
            return _classify(prompt, system, response_mime_type)

        deep_research.llm.generate_text = fake_generate

        output = await deep_research.deep_research("topic", breadth=1, max_iterations=1, verify=False)
        self.assertNotIn("## Verification", output)
        self.assertIn("## Sources", output)

    async def test_not_configured_raises_tool_error(self):
        deep_research.llm.is_configured = lambda: False
        with self.assertRaises(ToolError):
            await deep_research.deep_research("anything")

    async def test_no_crawlable_sources_raises_tool_error(self):
        async def fake_generate(prompt, *, model=None, system=None, temperature=0.2, response_mime_type=None, **kwargs):
            return _classify(prompt, system, response_mime_type)

        async def failing_fetch(target):
            raise RuntimeError("blocked")

        deep_research.llm.generate_text = fake_generate
        deep_research.content.fetch_auto = failing_fetch
        with self.assertRaises(ToolError):
            await deep_research.deep_research("anything", max_iterations=1)

    async def test_plan_falls_back_to_query_on_bad_json(self):
        async def bad_json(prompt, *, model=None, system=None, temperature=0.2, response_mime_type=None, **kwargs):
            raise ValueError("not json")

        deep_research.llm.generate_text = bad_json
        plan = await deep_research._plan("my question", None)
        self.assertEqual(plan.subquestions, ["my question"])
        self.assertEqual(plan.outline, [])

    async def test_search_fanout_dedupes_and_skips_seen(self):
        seen = {"https://example.com/0"}
        merged = await deep_research._search_fanout(["q1", "q2"], None, seen)
        urls = [r.url for r in merged]
        self.assertNotIn("https://example.com/0", urls)  # already seen -> skipped
        self.assertEqual(len(urls), len(set(urls)))  # deduped across the two queries


if __name__ == "__main__":
    unittest.main()
