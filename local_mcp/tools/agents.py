"""MCP tool handlers for defining and running multi-agent teams."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from local_mcp.agents import runner, teams, toolbelt
from local_mcp.llm import client as llm
from local_mcp.shared.errors import tool_error

AGENTS_JSON_DESCRIPTION = (
    "JSON list of agents, in run order. Each agent is an object with: "
    "`name` (unique), `role` (its system prompt), optional `tools` (list drawn from: "
    "web_search, web_fetch, extract_urls, parse_document), and optional `model` override. "
    'Example: [{"name": "researcher", "role": "Find facts with sources.", "tools": ["web_search", "web_fetch"]}, '
    '{"name": "writer", "role": "Write the final answer from the findings."}]. '
    "Keep teams small: 2-3 agents run best on local models."
)


async def define_agent_team(
    name: Annotated[str, Field(description="Team name, used as its slug. Reuse a name with overwrite=true to update it.")],
    agents: Annotated[str, Field(description=AGENTS_JSON_DESCRIPTION)],
    description: Annotated[str, Field(description="Optional one-line description of what the team is for.")] = "",
    overwrite: Annotated[bool, Field(description="Replace an existing team with the same name.")] = False,
) -> str:
    """Define (or update) a reusable multi-agent team that run_agent_team can execute."""
    try:
        team, path = teams.save_team(name=name, agents_json=agents, description=description, overwrite=overwrite)
    except ValueError as err:
        raise tool_error(str(err))

    lines = [f"Agent team '{team.slug}' saved ({path}).", "Agents (run in order):"]
    lines.extend(_describe_agent(agent) for agent in team.agents)
    lines.append("")
    lines.append(f'Run it with: run_agent_team(team="{team.slug}", task="...").')
    return "\n".join(lines)


async def run_agent_team(
    team: Annotated[str, Field(description="Name of a defined team, or a built-in preset: research, research-review.")],
    task: Annotated[str, Field(description="The task or question the team should work on.")],
    model: Annotated[str, Field(description="Optional model override for every agent. Empty uses the provider default.")] = "",
    max_tool_calls: Annotated[
        int,
        Field(description="Maximum tool calls each agent may make before it must answer.", ge=0, le=20),
    ] = runner.DEFAULT_MAX_TOOL_CALLS,
    include_transcript: Annotated[
        bool,
        Field(description="Include every agent's full hand-off message and tool calls, not just the final answer."),
    ] = False,
) -> str:
    """Run a multi-agent team on a task: agents work in sequence, using tools, and the last agent answers."""
    cleaned_task = (task or "").strip()
    if not cleaned_task:
        raise tool_error("A non-empty task is required.")
    if not llm.is_configured():
        raise tool_error(llm.not_configured_message())

    try:
        definition = teams.load_team(team)
    except ValueError as err:
        raise tool_error(str(err))

    try:
        run = await runner.run_team(definition, cleaned_task, model=model.strip(), max_tool_calls=max_tool_calls)
    except llm.LLMError as err:
        raise tool_error(str(err))

    return _format_run(run, include_transcript=include_transcript)


async def list_agent_teams() -> str:
    """List defined agent teams and built-in presets, with their agents and tools."""
    try:
        definitions = teams.list_teams()
    except ValueError as err:
        raise tool_error(str(err))

    if not definitions:
        return "No agent teams found. Create one with define_agent_team."

    lines = ["Agent teams:"]
    for team in definitions:
        source = "built-in preset" if team.builtin else "saved"
        lines.append(f"- {team.slug} ({source}): {team.description or 'no description'}")
        lines.extend(f"  {_describe_agent(agent)}" for agent in team.agents)
    lines.append("")
    lines.append(f"Available agent tools: {', '.join(sorted(toolbelt.TOOLS))}.")
    return "\n".join(lines)


async def delete_agent_team(
    name: Annotated[str, Field(description="Name or slug of the saved team to delete.")],
) -> str:
    """Delete a saved agent team. Built-in presets cannot be deleted."""
    try:
        return teams.delete_team(name)
    except ValueError as err:
        raise tool_error(str(err))


def _describe_agent(agent: teams.AgentSpec) -> str:
    tools = ", ".join(agent.tools) if agent.tools else "no tools"
    model = f", model={agent.model}" if agent.model else ""
    return f"- {agent.name}: tools=[{tools}]{model}"


def _format_run(run: runner.TeamRun, *, include_transcript: bool) -> str:
    lines = [run.final_output or "(the team produced no output)", "", "---", f"Team run: {run.team.slug}"]
    for agent_run in run.agent_runs:
        summary = f"- {agent_run.name}: {len(agent_run.tool_calls)} tool call(s)"
        if agent_run.notes:
            summary += f" ({'; '.join(agent_run.notes)})"
        lines.append(summary)

    if include_transcript:
        lines.extend(["", "Transcript:"])
        for agent_run in run.agent_runs:
            lines.append(f"\n### {agent_run.name}")
            for record in agent_run.tool_calls:
                lines.append(f"- called {record.tool}({record.arguments}) -> {record.result_preview!r}")
            lines.append(agent_run.output)
    return "\n".join(lines)
