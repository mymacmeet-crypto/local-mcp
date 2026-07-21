"""LangGraph-powered sequential engine that runs a team of tool-calling agents.

Agents run one after another (on a local model "parallel" agents would
serialize anyway — every agent is another call into the same model). Each agent
sees the task plus every previous agent's output; agents with tools run as a
LangGraph ReAct agent (``langgraph.prebuilt.create_react_agent`` over
``ChatOllama``) that may call its allowed toolbelt tools before producing its
hand-off message. The last agent's message is the team's final answer.

LangGraph is an optional extra (``pip install "local-mcp[agents-langgraph]"``)
so the serverless core stays light: this module imports it lazily, only when an
agent actually needs tools. Tool calling requires the Ollama backend; with
``LLM_PROVIDER=gemini`` agents still run, but text-only through
``llm.generate_text`` — as do agents without tools, which need no LangGraph.
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

_INSTALL_HINT = (
    "Agent teams with tools need the LangGraph engine, which is an optional extra. "
    'Install it with: pip install "local-mcp[agents-langgraph]"'
)


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

    # Tool calling drives Ollama through LangChain; other providers run text-only.
    if tools and llm.PROVIDER != "ollama":
        agent_run.notes.append(
            f"Tool calling requires LLM_PROVIDER=ollama; agent '{agent.name}' ran without its tools."
        )
        tools = []

    # No tools (or no budget for them) means no graph: one plain generation call.
    if not tools or max_tool_calls <= 0:
        agent_run.output = (
            await llm.generate_text(user, model=resolved_model, system=system, temperature=TEMPERATURE)
        ).strip()
        return agent_run

    await _run_react_agent(
        agent_run,
        tools=tools,
        system=system,
        user=user,
        model=resolved_model,
        max_tool_calls=max_tool_calls,
    )
    return agent_run


async def _run_react_agent(
    agent_run: AgentRun,
    *,
    tools: list[toolbelt.AgentTool],
    system: str,
    user: str,
    model: str | None,
    max_tool_calls: int,
) -> None:
    """Run one agent as a LangGraph ReAct graph, filling in the AgentRun in place."""
    try:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_core.tools import StructuredTool
        from langgraph.errors import GraphRecursionError
        from langgraph.prebuilt import create_react_agent
    except ImportError as err:
        raise llm.LLMError(_INSTALL_HINT) from err

    allowed = {tool.name for tool in tools}
    counter = {"used": 0}
    graph = create_react_agent(
        _build_chat_model(model),
        [
            _langchain_tool(
                StructuredTool,
                spec,
                agent_run=agent_run,
                allowed=allowed,
                budget=max_tool_calls,
                counter=counter,
            )
            for spec in tools
        ],
    )

    # Belt and braces on the budget: the wrappers stop executing tools once it
    # is spent, and the recursion limit caps the graph at the budgeted rounds
    # plus one "budget exhausted" round and the final answer step.
    config = {"recursion_limit": 2 * max_tool_calls + 4}
    state = {"messages": [SystemMessage(content=system), HumanMessage(content=user)]}
    try:
        result = await graph.ainvoke(state, config=config)
        messages = result.get("messages") or []
    except GraphRecursionError:
        agent_run.notes.append(
            f"Agent '{agent_run.name}' hit the graph step limit before finishing; its output may be incomplete."
        )
        messages = []

    output = ""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            output = _message_text(message).strip()
            if output:
                break
    agent_run.output = output or "(no output)"


def _build_chat_model(model: str | None):
    """Build the ChatOllama model for one agent (kept separate so tests can fake it)."""
    try:
        from langchain_ollama import ChatOllama
    except ImportError as err:
        raise llm.LLMError(_INSTALL_HINT) from err

    resolved = (model or "").strip() or ollama.DEFAULT_MODEL
    return ChatOllama(model=resolved, base_url=ollama.HOST, temperature=TEMPERATURE)


def _langchain_tool(structured_tool_cls, spec, *, agent_run, allowed, budget, counter):
    """Wrap one toolbelt tool as an async LangChain StructuredTool.

    The wrapper keeps the toolbelt's guarantees — allowlist checks, result
    truncation, errors as text — and records every call on the AgentRun.
    """

    async def run_tool(**kwargs):
        if counter["used"] >= budget:
            return (
                f"Error: tool budget of {budget} calls is exhausted. "
                "Write your final hand-off message now using what you have."
            )
        counter["used"] += 1
        result = await toolbelt.call_tool(spec.name, kwargs, allowed=allowed)
        agent_run.tool_calls.append(
            ToolCallRecord(
                agent=agent_run.name,
                tool=spec.name,
                arguments=dict(kwargs),
                result_preview=result[:200],
            )
        )
        if counter["used"] >= budget:
            note = f"Tool budget of {budget} calls reached; asked for a final answer."
            if note not in agent_run.notes:
                agent_run.notes.append(note)
        return result

    return structured_tool_cls.from_function(
        coroutine=run_tool,
        name=spec.name,
        description=spec.description,
        args_schema=spec.parameters,
    )


def _message_text(message) -> str:
    """Flatten an AIMessage's content, which may be a string or content blocks."""
    content = getattr(message, "content", "")
    if isinstance(content, list):
        parts = [part.get("text", "") if isinstance(part, dict) else str(part) for part in content]
        return "".join(parts)
    return str(content or "")


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
