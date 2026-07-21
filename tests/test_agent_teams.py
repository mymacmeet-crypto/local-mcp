import json
import os
import tempfile
import unittest
from importlib.util import find_spec

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


_HAS_AUTOGEN = find_spec("autogen_agentchat") is not None


class RunnerTests(TeamDirMixin, unittest.IsolatedAsyncioTestCase):
    """Dependency-free runner paths: missing-engine error and text-only fallback."""

    def setUp(self):
        self._use_temp_team_dir()
        self._orig_provider = runner.llm.PROVIDER
        self._orig_generate = runner.llm.generate_text
        self._orig_call_tool = runner.toolbelt.call_tool
        self._orig_load = runner._load_autogen
        self._orig_build = runner._build_model_client
        runner.llm.PROVIDER = "ollama"

    def tearDown(self):
        runner.llm.PROVIDER = self._orig_provider
        runner.llm.generate_text = self._orig_generate
        runner.toolbelt.call_tool = self._orig_call_tool
        runner._load_autogen = self._orig_load
        runner._build_model_client = self._orig_build
        self._restore_team_dir()

    async def test_missing_autogen_raises_install_hint(self):
        team, _ = teams.save_team(name="crew", agents_json=TWO_AGENTS)
        if _HAS_AUTOGEN:
            # AutoGen is installed in this environment; simulate its absence
            # through the same lazy-import indirection run_team relies on.
            def _absent():
                raise runner.llm.LLMError(runner.AUTOGEN_INSTALL_HINT)

            runner._load_autogen = _absent

        with self.assertRaises(runner.llm.LLMError) as ctx:
            await runner.run_team(team, "what is x?")
        self.assertIn("agents-autogen", str(ctx.exception))

    async def test_non_ollama_provider_runs_text_only(self):
        team, _ = teams.save_team(name="crew", agents_json=TWO_AGENTS)
        runner.llm.PROVIDER = "gemini"
        prompts = []

        async def fake_generate(prompt, *, model=None, system=None, temperature=0.2, **kwargs):
            prompts.append(prompt)
            if "researcher" in (system or "").lower() and "agent 1 of" in (system or "").lower():
                return "RESEARCH NOTES"
            return "text-only output"

        def no_engine(*args, **kwargs):
            raise AssertionError("AutoGen engine must not be built for non-ollama providers")

        runner.llm.generate_text = fake_generate
        runner._build_model_client = no_engine

        run = await runner.run_team(team, "task")

        self.assertEqual(run.final_output, "text-only output")
        self.assertEqual([r.name for r in run.agent_runs], ["researcher", "writer"])
        # researcher has web_search, so its tools are dropped with a note; writer has none.
        self.assertTrue(run.agent_runs[0].notes)
        self.assertFalse(run.agent_runs[1].notes)
        # The writer's prompt contains the researcher's hand-off (sequential).
        self.assertIn("RESEARCH NOTES", prompts[-1])


@unittest.skipUnless(_HAS_AUTOGEN, "autogen-agentchat not installed")
class RunnerEngineTests(TeamDirMixin, unittest.IsolatedAsyncioTestCase):
    """Real AutoGen engine, driven by ReplayChatCompletionClient (no Ollama server)."""

    MODEL_INFO = {
        "vision": False,
        "function_calling": True,
        "json_output": True,
        "family": "unknown",
        "structured_output": True,
    }

    def setUp(self):
        self._use_temp_team_dir()
        self._orig_provider = runner.llm.PROVIDER
        self._orig_build = runner._build_model_client
        self._orig_call_tool = runner.toolbelt.call_tool
        runner.llm.PROVIDER = "ollama"

    def tearDown(self):
        runner.llm.PROVIDER = self._orig_provider
        runner._build_model_client = self._orig_build
        runner.toolbelt.call_tool = self._orig_call_tool
        self._restore_team_dir()

    def _replay(self, responses):
        """A ReplayChatCompletionClient that also records the messages it receives."""
        from autogen_ext.models.replay import ReplayChatCompletionClient

        model_info = self.MODEL_INFO

        class _RecordingReplay(ReplayChatCompletionClient):
            def __init__(self, chat_completions):
                super().__init__(chat_completions, model_info=model_info)
                self.recorded_inputs = []

            async def create(self, messages, **kwargs):
                self.recorded_inputs.append([getattr(m, "content", m) for m in messages])
                return await super().create(messages, **kwargs)

        return _RecordingReplay(responses)

    async def test_sequential_handoff_records_each_agent(self):
        team, _ = teams.save_team(
            name="crew",
            agents_json=json.dumps(
                [
                    {"name": "researcher", "role": "Find facts."},
                    {"name": "writer", "role": "Write the answer."},
                ]
            ),
        )
        client = self._replay(["FINDINGS: sky scatters blue light", "FINAL: the sky is blue"])
        runner._build_model_client = lambda model_name: client

        run = await runner.run_team(team, "why is the sky blue?")

        self.assertEqual([r.name for r in run.agent_runs], ["researcher", "writer"])
        self.assertEqual(run.agent_runs[0].output, "FINDINGS: sky scatters blue light")
        self.assertEqual(run.final_output, "FINAL: the sky is blue")
        # The writer's model call saw the researcher's hand-off (sequential order).
        writer_inputs = " ".join(str(part) for part in client.recorded_inputs[1])
        self.assertIn("sky scatters blue light", writer_inputs)

    async def test_tool_budget_caps_recorded_calls(self):
        from autogen_core import FunctionCall
        from autogen_core.models import CreateResult, RequestUsage

        team, _ = teams.save_team(
            name="crew",
            agents_json=json.dumps(
                [{"name": "researcher", "role": "Find facts.", "tools": ["web_search"]}]
            ),
        )

        executed = []

        async def fake_call_tool(name, arguments, *, allowed):
            executed.append(name)
            return "search result"

        runner.toolbelt.call_tool = fake_call_tool

        # One turn asks for three tool calls at once; the budget is two.
        parallel = CreateResult(
            finish_reason="function_calls",
            content=[
                FunctionCall(id=f"c{i}", name="web_search", arguments=json.dumps({"query": q}))
                for i, q in enumerate(("a", "b", "c"))
            ],
            usage=RequestUsage(prompt_tokens=0, completion_tokens=0),
            cached=False,
        )
        client = self._replay([parallel, "FINAL after budget"])
        runner._build_model_client = lambda model_name: client

        run = await runner.run_team(team, "task", max_tool_calls=2)
        researcher = run.agent_runs[0]

        self.assertEqual(researcher.output, "FINAL after budget")
        self.assertEqual(len(researcher.tool_calls), 2)  # capped at the budget
        self.assertEqual(len(executed), 2)  # the 3rd call short-circuited before toolbelt
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
