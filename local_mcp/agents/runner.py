"""Built-in sequential engine that runs a team of tool-calling agents.

Agents run one after another (on a local model "parallel" agents would
serialize anyway — every agent is another call into the same model). Each agent
sees the task plus every previous agent's output, and may call its allowed
tools through Ollama function calling before producing its hand-off message.
The last agent's message is the team's final answer.

Tool calling requires the Ollama backend; with ``LLM_PROVIDER=gemini`` agents
still run, but text-only through ``llm.generate_text``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from local_mcp.agents import toolbelt
from local_mcp.agents.teams import AgentSpec, TeamDefinition
from local_mcp.llm import client as llm
from local_mcp.ollama import client as ollama

DEFAULT_MAX_TOOL_CALLS = int(os.environ.get("LOCAL_MCP_AGENT_MAX_TOOL_CALLS", "6"))
TEMPERATURE = float(os.environ.get("LOCAL_MCP_AGENT_TEMPERATURE", "0.2"))


@dataclass
class ToolCallRecord:
    agent: str
    tool: str
    arguments: dict
    result_preview: str


@dataclass
class AgentRun:
    name: str
    output: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class TeamRun:
    team: TeamDefinition
    task: str
    agent_runs: list[AgentRun] = field(default_factory=list)

    @property
    def final_output(self) -> str:
        return self.agent_runs[-1].output if self.agent_runs else ""


async def run_team(
    team: TeamDefinition,
    task: str,
    *,
    model: str = "",
    max_tool_calls: int | None = None,
) -> TeamRun:
    """Run every agent in order, feeding each the previous agents' outputs."""
    budget = DEFAULT_MAX_TOOL_CALLS if max_tool_calls is None else max(0, max_tool_calls)
    run = TeamRun(team=team, task=task)
    for position, agent in enumerate(team.agents):
        agent_run = await _run_agent(
            agent,
            team=team,
            task=task,
            position=position,
            previous=run.agent_runs,
            model=model,
            max_tool_calls=budget,
        )
        run.agent_runs.append(agent_run)
    return run


async def _run_agent(
    agent: AgentSpec,
    *,
    team: TeamDefinition,
    task: str,
    position: int,
    previous: list[AgentRun],
    model: str,
    max_tool_calls: int,
) -> AgentRun:
    agent_run = AgentRun(name=agent.name, output="")
    resolved_model = agent.model or model or None
    tools = toolbelt.tools_for(agent.tools)
    system = _system_prompt(agent, team, position)
    user = _user_prompt(task, previous)

    # Tool calling is an Ollama /api/chat feature; other providers run text-only.
    if tools and llm.PROVIDER != "ollama":
        agent_run.notes.append(
            f"Tool calling requires LLM_PROVIDER=ollama; agent '{agent.name}' ran without its tools."
        )
        tools = []

    if not tools:
        agent_run.output = (
            await llm.generate_text(user, model=resolved_model, system=system, temperature=TEMPERATURE)
        ).strip()
        return agent_run

    schemas = toolbelt.ollama_schemas(tools)
    allowed = {tool.name for tool in tools}
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    calls_used = 0
    while True:
        offer_tools = schemas if calls_used < max_tool_calls else None
        message = await ollama.chat(
            messages,
            model=resolved_model,
            tools=offer_tools,
            temperature=TEMPERATURE,
        )
        tool_calls = message.get("tool_calls") or []
        if not tool_calls or offer_tools is None:
            agent_run.output = str(message.get("content") or "").strip()
            if not agent_run.output:
                agent_run.output = "(no output)"
            return agent_run

        messages.append(message)
        for call in tool_calls:
            function = call.get("function") or {}
            name = str(function.get("name") or "").strip()
            arguments = function.get("arguments") or {}
            # Every requested call gets a tool message, so the transcript stays
            # consistent even when the budget runs out mid-batch.
            if calls_used >= max_tool_calls:
                result = (
                    f"Error: tool budget of {max_tool_calls} calls is exhausted. "
                    "Write your final hand-off message now using what you have."
                )
            else:
                result = await toolbelt.call_tool(name, arguments, allowed=allowed)
                calls_used += 1
                agent_run.tool_calls.append(
                    ToolCallRecord(
                        agent=agent.name,
                        tool=name,
                        arguments=arguments if isinstance(arguments, dict) else {},
                        result_preview=result[:200],
                    )
                )
            messages.append({"role": "tool", "tool_name": name, "content": result})
        if calls_used >= max_tool_calls:
            note = f"Tool budget of {max_tool_calls} calls reached; asked for a final answer."
            if note not in agent_run.notes:
                agent_run.notes.append(note)
            messages.append(
                {
                    "role": "user",
                    "content": "Your tool budget is used up. Write your final hand-off message now using what you have.",
                }
            )


def _system_prompt(agent: AgentSpec, team: TeamDefinition, position: int) -> str:
    teammates = ", ".join(spec.name for spec in team.agents)
    lines = [
        f"You are '{agent.name}', agent {position + 1} of {len(team.agents)} in the team '{team.name}' ({teammates}).",
        "The team works sequentially: each agent reads the task and previous agents' hand-offs, then writes its own.",
        "Your hand-off message must be plain text/Markdown, self-contained, and useful to the next agent.",
        "",
        agent.role.strip(),
    ]
    if position == len(team.agents) - 1:
        lines.insert(3, "You are the last agent: your message is the team's final answer to the user.")
    return "\n".join(lines)


def _user_prompt(task: str, previous: list[AgentRun]) -> str:
    sections = [f"Task:\n{task.strip()}"]
    for run in previous:
        sections.append(f"Hand-off from '{run.name}':\n{run.output}")
    return "\n\n".join(sections)
