import builtins
import importlib.util
import json
import os
import tempfile
import unittest

from local_mcp.agents import runner, teams, toolbelt
from local_mcp.shared.errors import ToolError
from local_mcp.tools import agents as agent_tools

TWO_AGENTS = json.dumps(
    [
        {"name": "researcher", "role": "Find facts.", "tools": ["web_search"]},
        {"name": "writer", "role": "Write the answer."},
    ]
)


class TeamDirMixin:
    def _use_temp_team_dir(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = os.environ.get(teams.AGENT_TEAM_DIR_ENV)
        os.environ[teams.AGENT_TEAM_DIR_ENV] = self._tmp.name

    def _restore_team_dir(self):
        if self._old_dir is None:
            os.environ.pop(teams.AGENT_TEAM_DIR_ENV, None)
        else:
            os.environ[teams.AGENT_TEAM_DIR_ENV] = self._old_dir
        self._tmp.cleanup()


class TeamCrudTests(TeamDirMixin, unittest.TestCase):
    def setUp(self):
        self._use_temp_team_dir()

    def tearDown(self):
        self._restore_team_dir()

    def test_save_load_list_delete_roundtrip(self):
        team, path = teams.save_team(name="My Crew", agents_json=TWO_AGENTS, description="demo")
        self.assertTrue(path.is_file())
        self.assertEqual(team.slug, "my-crew")

        loaded = teams.load_team("My Crew")
        self.assertEqual(loaded.agents[0].name, "researcher")
        self.assertEqual(loaded.agents[0].tools, ("web_search",))
        self.assertEqual(loaded.agents[1].tools, ())

        slugs = [entry.slug for entry in teams.list_teams()]
        self.assertIn("my-crew", slugs)
        self.assertIn("research", slugs)  # built-in preset listed too

        with self.assertRaises(ValueError):
            teams.save_team(name="My Crew", agents_json=TWO_AGENTS)  # no overwrite
        teams.save_team(name="My Crew", agents_json=TWO_AGENTS, overwrite=True)

        self.assertIn("Deleted", teams.delete_team("my-crew"))
        with self.assertRaises(ValueError):
            teams.load_team("my-crew")

    def test_parse_agents_validation(self):
        for bad in ("", "not json", "[]", '[{"role": "no name"}]', '[{"name": "a"}]'):
            with self.assertRaises(ValueError):
                teams.parse_agents(bad)
        with self.assertRaises(ValueError):
            teams.parse_agents('[{"name": "a", "role": "r"}, {"name": "a", "role": "r"}]')
        with self.assertRaises(ValueError):
            teams.parse_agents('[{"name": "a", "role": "r", "tools": ["nope"]}]')
        too_many = json.dumps([{"name": f"a{i}", "role": "r"} for i in range(teams.MAX_AGENTS + 1)])
        with self.assertRaises(ValueError):
            teams.parse_agents(too_many)

    def test_builtin_presets(self):
        preset = teams.load_team("research")
        self.assertTrue(preset.builtin)
        self.assertEqual([agent.name for agent in preset.agents], ["researcher", "writer"])
        with self.assertRaises(ValueError):
            teams.delete_team("research")

        # A saved team shadows the preset; deleting it restores the preset.
        teams.save_team(name="research", agents_json=TWO_AGENTS, overwrite=True)
        self.assertFalse(teams.load_team("research").builtin)
        self.assertIn("built-in preset", teams.delete_team("research"))
        self.assertTrue(teams.load_team("research").builtin)


class ToolbeltTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_tool_guards(self):
        allowed = {"web_search"}
        self.assertIn("unknown tool", await toolbelt.call_tool("nope", {}, allowed=allowed))
        self.assertIn("not allowed", await toolbelt.call_tool("web_fetch", {}, allowed=allowed))
        self.assertIn("not valid JSON", await toolbelt.call_tool("web_search", "{bad", allowed=allowed))

    async def test_call_tool_reports_handler_errors_as_text(self):
        original = toolbelt.TOOLS["web_search"]

        async def boom(**kwargs):
            raise RuntimeError("network down")

        toolbelt.TOOLS["web_search"] = toolbelt.AgentTool(
            name=original.name, description=original.description, parameters=original.parameters, handler=boom
        )
        try:
            result = await toolbelt.call_tool("web_search", {"query": "x"}, allowed={"web_search"})
        finally:
            toolbelt.TOOLS["web_search"] = original
        self.assertIn("network down", result)

    def test_truncation(self):
        text = "x" * (toolbelt.RESULT_CHAR_LIMIT + 100)
        truncated = toolbelt._truncate(text)
        self.assertLess(len(truncated), len(text))
        self.assertIn("truncated", truncated)


HAS_LANGGRAPH = importlib.util.find_spec("langgraph") is not None


class RunnerTests(TeamDirMixin, unittest.IsolatedAsyncioTestCase):
    """Runner paths that must work without langgraph installed."""

    def setUp(self):
        self._use_temp_team_dir()
        self._orig_generate = runner.llm.generate_text
        self._orig_provider = runner.llm.PROVIDER
        runner.llm.PROVIDER = "ollama"

    def tearDown(self):
        runner.llm.generate_text = self._orig_generate
        runner.llm.PROVIDER = self._orig_provider
        self._restore_team_dir()

    async def test_no_tools_agents_hand_off_sequentially(self):
        no_tools = json.dumps(
            [
                {"name": "planner", "role": "Plan the work."},
                {"name": "writer", "role": "Write the answer."},
            ]
        )
        team, _ = teams.save_team(name="crew", agents_json=no_tools)
        calls = []

        async def fake_generate(prompt, *, model=None, system=None, temperature=0.2, **kwargs):
            calls.append({"prompt": prompt, "system": system})
            return f"output-{len(calls)}"

        runner.llm.generate_text = fake_generate

        run = await runner.run_team(team, "what is x?")
        self.assertEqual(run.final_output, "output-2")
        self.assertEqual([r.name for r in run.agent_runs], ["planner", "writer"])
        self.assertIn("what is x?", calls[0]["prompt"])
        self.assertIn("planner", calls[0]["system"])
        # The writer sees the planner's hand-off.
        self.assertIn("Hand-off from 'planner':\noutput-1", calls[1]["prompt"])

    async def test_non_ollama_provider_runs_text_only(self):
        team, _ = teams.save_team(name="crew", agents_json=TWO_AGENTS)
        runner.llm.PROVIDER = "gemini"

        async def fake_generate(prompt, *, model=None, system=None, temperature=0.2, **kwargs):
            return "text-only output"

        runner.llm.generate_text = fake_generate

        run = await runner.run_team(team, "task")
        self.assertEqual(run.final_output, "text-only output")
        self.assertTrue(run.agent_runs[0].notes)  # tools were dropped with a note
        self.assertEqual(run.agent_runs[0].tool_calls, [])

    async def test_missing_langgraph_raises_llm_error_with_install_hint(self):
        team, _ = teams.save_team(name="crew", agents_json=TWO_AGENTS)

        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name.split(".")[0] in {"langgraph", "langchain_core", "langchain_ollama"}:
                raise ImportError(f"No module named {name!r} (blocked by test)")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = blocked_import
        try:
            with self.assertRaises(runner.llm.LLMError) as ctx:
                await runner.run_team(team, "task")
        finally:
            builtins.__import__ = real_import
        self.assertIn("agents-langgraph", str(ctx.exception))


@unittest.skipUnless(HAS_LANGGRAPH, "langgraph is not installed (pip install 'local-mcp[agents-langgraph]')")
class LangGraphEngineTests(TeamDirMixin, unittest.IsolatedAsyncioTestCase):
    """Exercise the real LangGraph graph with a scripted fake chat model."""

    def setUp(self):
        self._use_temp_team_dir()
        self._orig_generate = runner.llm.generate_text
        self._orig_provider = runner.llm.PROVIDER
        self._orig_build_model = runner._build_chat_model
        self._orig_call_tool = runner.toolbelt.call_tool
        runner.llm.PROVIDER = "ollama"

    def tearDown(self):
        runner.llm.generate_text = self._orig_generate
        runner.llm.PROVIDER = self._orig_provider
        runner._build_chat_model = self._orig_build_model
        runner.toolbelt.call_tool = self._orig_call_tool
        self._restore_team_dir()

    def _script_model(self, messages):
        """Make _build_chat_model return a fake model that replays `messages` in order."""
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

        class ScriptedModel(GenericFakeChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        model = ScriptedModel(messages=iter(messages))
        runner._build_chat_model = lambda name: model

    @staticmethod
    def _tool_call_message(name, args):
        from langchain_core.messages import AIMessage

        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call-1", "type": "tool_call"}])

    async def test_sequential_handoff_with_tool_calls(self):
        from langchain_core.messages import AIMessage

        team, _ = teams.save_team(name="crew", agents_json=TWO_AGENTS)
        self._script_model(
            [
                self._tool_call_message("web_search", {"query": "x"}),
                AIMessage(content="FINDINGS: fact [https://e.com]"),
            ]
        )
        tool_calls = []

        async def fake_call_tool(name, arguments, *, allowed):
            tool_calls.append((name, arguments, set(allowed)))
            return "search result"

        async def fake_generate(prompt, *, model=None, system=None, temperature=0.2, **kwargs):
            self.assertIn("FINDINGS: fact", prompt)  # writer sees the researcher hand-off
            self.assertIn("writer", (system or "").lower())
            return "FINAL ANSWER"

        runner.toolbelt.call_tool = fake_call_tool
        runner.llm.generate_text = fake_generate

        run = await runner.run_team(team, "what is x?")

        self.assertEqual(run.final_output, "FINAL ANSWER")
        self.assertEqual([r.name for r in run.agent_runs], ["researcher", "writer"])
        # The wrapper enforced the researcher's allowlist and recorded the call.
        self.assertEqual(tool_calls, [("web_search", {"query": "x"}, {"web_search"})])
        researcher = run.agent_runs[0]
        self.assertEqual(len(researcher.tool_calls), 1)
        self.assertEqual(researcher.tool_calls[0].tool, "web_search")
        self.assertEqual(researcher.tool_calls[0].result_preview, "search result")
        self.assertEqual(researcher.output, "FINDINGS: fact [https://e.com]")

    async def test_tool_budget_stops_execution(self):
        from langchain_core.messages import AIMessage

        solo = json.dumps([{"name": "researcher", "role": "Find facts.", "tools": ["web_search"]}])
        team, _ = teams.save_team(name="solo", agents_json=solo)
        self._script_model(
            [
                self._tool_call_message("web_search", {"query": "one"}),
                self._tool_call_message("web_search", {"query": "two"}),
                AIMessage(content="forced final"),
            ]
        )
        executed = []

        async def fake_call_tool(name, arguments, *, allowed):
            executed.append(arguments)
            return "result"

        runner.toolbelt.call_tool = fake_call_tool

        run = await runner.run_team(team, "task", max_tool_calls=1)
        researcher = run.agent_runs[0]
        self.assertEqual(researcher.output, "forced final")
        # Only the first call reached the toolbelt; the second got a budget error.
        self.assertEqual(executed, [{"query": "one"}])
        self.assertEqual(len(researcher.tool_calls), 1)
        self.assertTrue(researcher.notes)


class AgentToolHandlerTests(TeamDirMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._use_temp_team_dir()
        self._orig_run_team = agent_tools.runner.run_team
        self._orig_is_configured = agent_tools.llm.is_configured
        agent_tools.llm.is_configured = lambda: True

    def tearDown(self):
        agent_tools.runner.run_team = self._orig_run_team
        agent_tools.llm.is_configured = self._orig_is_configured
        self._restore_team_dir()

    async def test_define_list_delete(self):
        output = await agent_tools.define_agent_team(name="crew", agents=TWO_AGENTS, description="demo")
        self.assertIn("crew", output)
        self.assertIn("researcher", output)

        listing = await agent_tools.list_agent_teams()
        self.assertIn("crew (saved)", listing)
        self.assertIn("research (built-in preset)", listing)

        self.assertIn("Deleted", await agent_tools.delete_agent_team("crew"))
        with self.assertRaises(ToolError):
            await agent_tools.delete_agent_team("crew")

    async def test_define_rejects_invalid_agents(self):
        with self.assertRaises(ToolError):
            await agent_tools.define_agent_team(name="crew", agents="not json")

    async def test_run_formats_final_answer_and_transcript(self):
        await agent_tools.define_agent_team(name="crew", agents=TWO_AGENTS)

        async def fake_run_team(definition, task, *, model="", max_tool_calls=None):
            run = runner.TeamRun(team=definition, task=task)
            researcher = runner.AgentRun(name="researcher", output="notes")
            researcher.tool_calls.append(
                runner.ToolCallRecord(agent="researcher", tool="web_search", arguments={"query": "x"}, result_preview="r")
            )
            run.agent_runs.append(researcher)
            run.agent_runs.append(runner.AgentRun(name="writer", output="THE ANSWER"))
            return run

        agent_tools.runner.run_team = fake_run_team

        brief = await agent_tools.run_agent_team(team="crew", task="question")
        self.assertTrue(brief.startswith("THE ANSWER"))
        self.assertIn("researcher: 1 tool call(s)", brief)
        self.assertNotIn("Transcript:", brief)

        full = await agent_tools.run_agent_team(team="crew", task="question", include_transcript=True)
        self.assertIn("Transcript:", full)
        self.assertIn("web_search", full)

    async def test_run_requires_task_and_known_team(self):
        with self.assertRaises(ToolError):
            await agent_tools.run_agent_team(team="research", task="   ")
        with self.assertRaises(ToolError):
            await agent_tools.run_agent_team(team="missing-team", task="question")


if __name__ == "__main__":
    unittest.main()
