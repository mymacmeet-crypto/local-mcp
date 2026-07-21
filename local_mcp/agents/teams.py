"""Persist and validate multi-agent team definitions (the CRUD layer).

A team is a small ordered list of agents (2-3 roles work best on local models —
each agent is another call into the same model, so they serialize). Definitions
are stored one JSON file per team under ``LOCAL_MCP_AGENT_TEAM_DIR``; a couple
of built-in presets are always available without defining anything.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from local_mcp.agents import toolbelt

AGENT_TEAM_DIR_ENV = "LOCAL_MCP_AGENT_TEAM_DIR"
MAX_AGENTS = int(os.environ.get("LOCAL_MCP_AGENT_TEAM_MAX_AGENTS", "5"))


@dataclass(frozen=True)
class AgentSpec:
    """One role in a team: a name, a system-prompt role, and an optional tool allowlist."""

    name: str
    role: str
    tools: tuple[str, ...] = ()
    model: str = ""


@dataclass(frozen=True)
class TeamDefinition:
    name: str
    slug: str
    description: str
    agents: tuple[AgentSpec, ...]
    builtin: bool = False


BUILTIN_TEAMS: dict[str, TeamDefinition] = {
    "research": TeamDefinition(
        name="research",
        slug="research",
        description="Built-in preset: a researcher gathers sources with web tools, then a writer composes the answer.",
        agents=(
            AgentSpec(
                name="researcher",
                role=(
                    "You are a careful web researcher. Use your tools to find and read relevant, "
                    "trustworthy sources for the task. Gather concrete facts with their source URLs. "
                    "Finish with a compact bullet list of findings, each followed by its source URL."
                ),
                tools=("web_search", "web_fetch"),
            ),
            AgentSpec(
                name="writer",
                role=(
                    "You are a clear technical writer. Using only the researcher's findings, write the "
                    "final answer to the task in well-structured Markdown. Cite source URLs inline. "
                    "Do not invent facts that are not in the findings."
                ),
            ),
        ),
        builtin=True,
    ),
    "research-review": TeamDefinition(
        name="research-review",
        slug="research-review",
        description="Built-in preset: researcher -> writer -> reviewer who fact-checks the draft against the findings.",
        agents=(
            AgentSpec(
                name="researcher",
                role=(
                    "You are a careful web researcher. Use your tools to find and read relevant, "
                    "trustworthy sources for the task. Gather concrete facts with their source URLs. "
                    "Finish with a compact bullet list of findings, each followed by its source URL."
                ),
                tools=("web_search", "web_fetch"),
            ),
            AgentSpec(
                name="writer",
                role=(
                    "You are a clear technical writer. Using only the researcher's findings, write the "
                    "final answer to the task in well-structured Markdown with inline source citations."
                ),
            ),
            AgentSpec(
                name="reviewer",
                role=(
                    "You are a skeptical reviewer. Compare the writer's draft against the researcher's "
                    "findings. Fix unsupported claims, missing citations, and unclear wording, then "
                    "output the corrected final answer in full."
                ),
            ),
        ),
        builtin=True,
    ),
}


def team_root() -> Path:
    configured = (os.environ.get(AGENT_TEAM_DIR_ENV) or "").strip() or ".tmp/agent_teams"
    root = Path(configured).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_.-]+", "-", (name or "").lower()).strip("-._")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise ValueError("name must contain at least one letter or number.")
    return slug[:80]


def parse_agents(agents_json: str) -> tuple[AgentSpec, ...]:
    """Parse and validate the ``agents`` JSON: a list of {name, role, tools?, model?}."""
    raw = (agents_json or "").strip()
    if not raw:
        raise ValueError("agents is required: a JSON list of {name, role, tools?, model?} objects.")
    try:
        data = json.loads(raw)
    except ValueError as err:
        raise ValueError(f"agents is not valid JSON: {err}")
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise ValueError("agents must be a non-empty JSON list of agent objects.")
    if len(data) > MAX_AGENTS:
        raise ValueError(
            f"Too many agents ({len(data)}). Keep teams small (2-3 roles run best on local "
            f"models); the maximum is {MAX_AGENTS}."
        )

    specs: list[AgentSpec] = []
    seen: set[str] = set()
    for index, entry in enumerate(data, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Agent #{index} must be a JSON object with name and role.")
        name = str(entry.get("name") or "").strip()
        role = str(entry.get("role") or entry.get("prompt") or "").strip()
        if not name:
            raise ValueError(f"Agent #{index} is missing a name.")
        if not role:
            raise ValueError(f"Agent '{name}' is missing a role (its system prompt).")
        key = name.lower()
        if key in seen:
            raise ValueError(f"Duplicate agent name: {name!r}. Agent names must be unique.")
        seen.add(key)

        tools_value = entry.get("tools") or []
        if isinstance(tools_value, str):
            tools_value = [item for item in re.split(r"[\s,]+", tools_value) if item]
        if not isinstance(tools_value, list):
            raise ValueError(f"Agent '{name}' tools must be a list of tool names.")
        tools: list[str] = []
        for tool in tools_value:
            tool_name = str(tool).strip()
            if tool_name not in toolbelt.TOOLS:
                available = ", ".join(sorted(toolbelt.TOOLS))
                raise ValueError(f"Agent '{name}' requests unknown tool {tool_name!r}. Available tools: {available}.")
            if tool_name not in tools:
                tools.append(tool_name)

        specs.append(
            AgentSpec(
                name=name,
                role=role,
                tools=tuple(tools),
                model=str(entry.get("model") or "").strip(),
            )
        )
    return tuple(specs)


def save_team(
    *,
    name: str,
    agents_json: str,
    description: str = "",
    overwrite: bool = False,
) -> tuple[TeamDefinition, Path]:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("name is required.")
    slug = slugify(clean_name)
    agents = parse_agents(agents_json)

    path = team_root() / f"{slug}.json"
    if path.exists() and not overwrite:
        raise ValueError(f"Team '{slug}' already exists. Set overwrite=true to replace it.")

    team = TeamDefinition(name=clean_name, slug=slug, description=(description or "").strip(), agents=agents)
    payload = {
        "name": team.name,
        "slug": team.slug,
        "description": team.description,
        "agents": [
            {"name": agent.name, "role": agent.role, "tools": list(agent.tools), "model": agent.model}
            for agent in team.agents
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return team, path


def load_team(name: str) -> TeamDefinition:
    slug = slugify(name)
    path = team_root() / f"{slug}.json"
    if path.is_file():
        return _team_from_file(path)
    if slug in BUILTIN_TEAMS:
        return BUILTIN_TEAMS[slug]
    available = ", ".join(sorted({team.slug for team in list_teams()})) or "none"
    raise ValueError(f"Unknown team {slug!r}. Available teams: {available}.")


def list_teams() -> list[TeamDefinition]:
    """Saved teams plus built-in presets; a saved team shadows a preset with the same slug."""
    teams: dict[str, TeamDefinition] = dict(BUILTIN_TEAMS)
    root = team_root()
    for path in sorted(root.glob("*.json")):
        try:
            team = _team_from_file(path)
        except ValueError:
            continue
        teams[team.slug] = team
    return sorted(teams.values(), key=lambda team: team.slug)


def delete_team(name: str) -> str:
    slug = slugify(name)
    path = team_root() / f"{slug}.json"
    if path.is_file():
        path.unlink()
        if slug in BUILTIN_TEAMS:
            return f"Deleted saved team '{slug}'. The built-in preset with the same name is active again."
        return f"Deleted team '{slug}' ({path})."
    if slug in BUILTIN_TEAMS:
        raise ValueError(f"'{slug}' is a built-in preset and cannot be deleted. Save a team with the same name to override it.")
    raise ValueError(f"No saved team named {slug!r} was found.")


def _team_from_file(path: Path) -> TeamDefinition:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise ValueError(f"Could not read team file {path}: {err}")
    if not isinstance(data, dict):
        raise ValueError(f"Team file {path} is not a JSON object.")
    agents = parse_agents(json.dumps(data.get("agents") or []))
    name = str(data.get("name") or path.stem).strip() or path.stem
    return TeamDefinition(
        name=name,
        slug=slugify(str(data.get("slug") or name)),
        description=str(data.get("description") or "").strip(),
        agents=agents,
    )
