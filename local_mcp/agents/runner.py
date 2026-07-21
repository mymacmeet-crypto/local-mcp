"""AutoGen-backed sequential engine that runs a team of tool-calling agents.

Orchestration is delegated to Microsoft AutoGen (autogen-agentchat >= 0.4):
each team member becomes an ``AssistantAgent`` talking to the local Ollama
server through ``autogen_ext``'s Ollama model client, with its allowed
local-mcp tools exposed as plain async functions. Agents still run one after
another (on a local model "parallel" agents would serialize anyway — every
agent is another call into the same model): each agent sees the task plus
every previous agent's hand-off, and the last agent's message is the team's
final answer.

AutoGen is an optional extra so the serverless core stays light — install it
with ``pip install "local-mcp[agents-autogen]"``. Without it, ``run_team``
raises ``LLMError`` with install instructions. With ``LLM_PROVIDER=gemini``
agents still run, but text-only through ``llm.generate_text`` (no AutoGen
needed).
"""

from __future__ import annotations

import contextlib
import inspect
import os
import re
from dataclasses import dataclass, field
from typing import Any

from local_mcp.agents import toolbelt
from local_mcp.agents.teams import AgentSpec, TeamDefinition
from local_mcp.llm import client as llm
from local_mcp.ollama import client as ollama

DEFAULT_MAX_TOOL_CALLS = int(os.environ.get("LOCAL_MCP_AGENT_MAX_TOOL_CALLS", "6"))
TEMPERATURE = float(os.environ.get("LOCAL_MCP_AGENT_TEMPERATURE", "0.2"))

AUTOGEN_INSTALL_HINT = (
    "Agent teams run on the AutoGen engine, which is an optional extra and is "
    'not installed. Install it with: pip install "local-mcp[agents-autogen]"'
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
    clients: dict[str, Any] = {}  # one model client per distinct model name
    try:
        for position, agent in enumerate(team.agents):
            agent_run = await _run_agent(
                agent,
                team=team,
                task=task,
                position=position,
                previous=run.agent_runs,
                model=model,
                max_tool_calls=budget,
                clients=clients,
            )
            run.agent_runs.append(agent_run)
    finally:
        for client in clients.values():
            with contextlib.suppress(Exception):
                await client.close()
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
    clients: dict[str, Any],
) -> AgentRun:
    agent_run = AgentRun(name=agent.name, output="")
    tools = toolbelt.tools_for(agent.tools)
    system = _system_prompt(agent, team, position)
    user = _user_prompt(task, previous)

    # The AutoGen engine drives Ollama; other providers run text-only.
    if llm.PROVIDER != "ollama":
        if tools:
            agent_run.notes.append(
                f"Tool calling requires LLM_PROVIDER=ollama; agent '{agent.name}' ran without its tools."
            )
        agent_run.output = (
            await llm.generate_text(
                user, model=agent.model or model or None, system=system, temperature=TEMPERATURE
            )
        ).strip()
        return agent_run

    assistant_cls = _load_autogen()
    resolved_model = (agent.model or model or ollama.DEFAULT_MODEL).strip() or ollama.DEFAULT_MODEL
    if resolved_model not in clients:
        clients[resolved_model] = _build_model_client(resolved_model)

    wrappers = _tool_functions(agent, tools, agent_run, max_tool_calls)
    kwargs: dict[str, Any] = {}
    if wrappers:
        kwargs["tools"] = wrappers
        # Always finish with a plain-text hand-off, even right after tool calls.
        kwargs["reflect_on_tool_use"] = True
        # Older 0.4.x AssistantAgents allow only one round of tool calls per run;
        # where supported, let the agent keep calling tools up to its budget.
        if "max_tool_iterations" in inspect.signature(assistant_cls.__init__).parameters:
            kwargs["max_tool_iterations"] = max(1, max_tool_calls)

    assistant = assistant_cls(
        name=_agent_id(agent.name),
        model_client=clients[resolved_model],
        system_message=system,
        **kwargs,
    )
    result = await assistant.run(task=user)
    agent_run.output = _final_text(result) or "(no output)"
    return agent_run


def _load_autogen() -> Any:
    """Import AutoGen's AssistantAgent lazily so the core install stays light."""
    try:
        from autogen_agentchat.agents import AssistantAgent
    except ImportError as err:
        raise llm.LLMError(AUTOGEN_INSTALL_HINT) from err
    return AssistantAgent


def _build_model_client(model_name: str) -> Any:
    """Build the Ollama model client the AssistantAgents talk through.

    Kept as a small indirection so tests can swap in AutoGen's
    ``ReplayChatCompletionClient`` without a real Ollama server.
    """
    try:
        from autogen_ext.models.ollama import OllamaChatCompletionClient
    except ImportError as err:
        raise llm.LLMError(AUTOGEN_INSTALL_HINT) from err
    return OllamaChatCompletionClient(
        model=model_name,
        host=ollama.HOST,
        options={"temperature": TEMPERATURE},
        # Local model names are arbitrary, so declare capabilities instead of
        # relying on autogen's known-model registry.
        model_info={
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "structured_output": True,
            "family": "unknown",
        },
    )


def _tool_functions(
    agent: AgentSpec,
    tools: list[toolbelt.AgentTool],
    agent_run: AgentRun,
    max_tool_calls: int,
) -> list[Any]:
    """Async wrappers (one per allowed tool) that AutoGen exposes to the model.

    Every call is routed through ``toolbelt.call_tool`` so the allowlist,
    error-as-text, and truncation behavior stay identical, and each executed
    call is recorded on the agent's run and counted against its budget.
    """
    if not tools:
        return []
    allowed = {tool.name for tool in tools}

    async def invoke(name: str, arguments: dict) -> str:
        if len(agent_run.tool_calls) >= max_tool_calls:
            note = f"Tool budget of {max_tool_calls} calls reached; asked for a final answer."
            if note not in agent_run.notes:
                agent_run.notes.append(note)
            return (
                f"Error: tool budget exhausted ({max_tool_calls} calls). "
                "Write your final hand-off message now using what you have."
            )
        result = await toolbelt.call_tool(name, arguments, allowed=allowed)
        agent_run.tool_calls.append(
            ToolCallRecord(agent=agent.name, tool=name, arguments=arguments, result_preview=result[:200])
        )
        return result

    wrappers: list[Any] = []
    if "web_search" in allowed:

        async def web_search(query: str, limit: int = 5) -> str:
            """Search the web (SearXNG) and get candidate source URLs for a query."""
            return await invoke("web_search", {"query": query, "limit": limit})

        wrappers.append(web_search)
    if "web_fetch" in allowed:

        async def web_fetch(url: str, max_chars: int = 20_000) -> str:
            """Fetch one web page and return its content as Markdown."""
            return await invoke("web_fetch", {"url": url, "max_chars": max_chars})

        wrappers.append(web_fetch)
    if "extract_urls" in allowed:

        async def extract_urls(url: str, limit: int = 50) -> str:
            """List URLs found on a page or site (sitemaps and page links)."""
            return await invoke("extract_urls", {"url": url, "limit": limit})

        wrappers.append(extract_urls)
    if "parse_document" in allowed:

        async def parse_document(document: str, pages: str = "") -> str:
            """Read a document (PDF, DOCX, ...) from a path or URL into Markdown."""
            return await invoke("parse_document", {"document": document, "pages": pages})

        wrappers.append(parse_document)
    return wrappers


def _final_text(result: Any) -> str:
    """The agent's final hand-off: the last plain-text message it produced."""
    for message in reversed(getattr(result, "messages", None) or []):
        if getattr(message, "source", "") == "user":
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def _agent_id(name: str) -> str:
    """AutoGen agent names must be identifiers; team agent names need not be."""
    cleaned = re.sub(r"\W+", "_", name).strip("_") or "agent"
    if cleaned[0].isdigit():
        cleaned = f"a_{cleaned}"
    return cleaned


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
