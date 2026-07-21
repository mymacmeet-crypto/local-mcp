# Agent teams — sub-agent orchestration

`local-mcp` can run a small **multi-agent team** on one task: an ordered list of role-based agents where each agent reads the task plus every previous agent's hand-off message, optionally calls tools, and writes its own hand-off. The last agent's message is the team's final answer.

This is the local, self-hosted equivalent of frontier "sub-agent orchestration" features (Claude Code's Agent tool, OpenAI AgentKit). The engine is a deliberately small built-in loop — no LangGraph/CrewAI dependency — so it deploys anywhere the server does, including serverless hosts.

## How a run works

```
run_agent_team(team="research", task="...")
  agent 1 (researcher)  -- may call web_search / web_fetch via Ollama function calling
      -> hand-off: findings with source URLs
  agent 2 (writer)      -- sees task + researcher hand-off
      -> hand-off: final Markdown answer  <- returned to you
```

Agents run **sequentially**, not in parallel. On a local model this is not a limitation: every agent is another call into the *same* model, so "parallel" agents would serialize anyway. Keep teams small — 2-3 roles work best; the hard cap is `LOCAL_MCP_AGENT_TEAM_MAX_AGENTS` (default 5).

## Tools agents can use

Each agent has a tool **allowlist** (empty by default). Available tools:

| Tool | Purpose |
| --- | --- |
| `web_search` | SearXNG search: candidate source URLs for a query. |
| `web_fetch` | Fetch one page as Markdown. |
| `extract_urls` | List URLs found on a page or site. |
| `parse_document` | Read a PDF/DOCX/... from a path or URL into Markdown. |

Tool calling uses Ollama's native function-calling API, so it requires `LLM_PROVIDER=ollama` (the default) and a model that supports tools (for example `qwen2.5`, `qwen3`, `llama3.1+`). With `LLM_PROVIDER=gemini` teams still run, but text-only: tool allowlists are dropped with a note in the run summary. Tool failures are returned to the agent as text (never crash the run), each result is truncated to `LOCAL_MCP_AGENT_TOOL_RESULT_CHARS` (default 8000), and each agent has a per-run budget of `max_tool_calls` (default `LOCAL_MCP_AGENT_MAX_TOOL_CALLS`, 6).

## Built-in presets

- **`research`** — `researcher` (web_search, web_fetch) → `writer`.
- **`research-review`** — `researcher` → `writer` → `reviewer` who fact-checks the draft against the findings.

Saving a team with the same name overrides a preset; deleting the saved team restores it.

## The tools

### `define_agent_team`

Saves a reusable team as JSON under `LOCAL_MCP_AGENT_TEAM_DIR` (default `.tmp/agent_teams`).

- `name`: team name (also its slug).
- `agents`: JSON list, in run order. Each agent: `name` (unique), `role` (its system prompt), optional `tools` (from the table above), optional `model` (per-agent model override).
- `description`, `overwrite`: optional.

Example `agents` value:

```json
[
  {"name": "researcher", "role": "Find concrete facts with source URLs.", "tools": ["web_search", "web_fetch"]},
  {"name": "skeptic", "role": "Challenge weak or unsupported findings.", "tools": ["web_fetch"]},
  {"name": "writer", "role": "Write the final answer from the surviving findings."}
]
```

### `run_agent_team`

- `team`: a saved team or preset name.
- `task`: what the team should work on.
- `model`: optional model override for every agent (per-agent `model` wins).
- `max_tool_calls`: per-agent tool budget (0-20, default 6).
- `include_transcript`: include every agent's full hand-off and tool calls, not just the final answer.

### `list_agent_teams` / `delete_agent_team`

List saved teams and presets (with each agent's tools), and delete saved teams. Presets cannot be deleted.

### `run_agent_task` (simple profile)

A one-call wrapper for weak tool-calling models: `run_agent_task(task, team="research")`.

## Configuration

```env
# LOCAL_MCP_AGENT_TEAM_DIR=~/Downloads/local-mcp/agent-teams
# LOCAL_MCP_AGENT_MAX_TOOL_CALLS=6
# LOCAL_MCP_AGENT_TEAM_MAX_AGENTS=5
# LOCAL_MCP_AGENT_TOOL_RESULT_CHARS=8000
# LOCAL_MCP_AGENT_TEMPERATURE=0.2
# Backend (shared with smart_search/deep_research):
# LLM_PROVIDER=ollama
# OLLAMA_HOST=http://127.0.0.1:11434
# OLLAMA_MODEL=qwen2.5:7b
```

## When to use what

- One question, one answer → `smart_search`.
- Broad question worth many sources and verification → `deep_research`.
- A repeatable workflow with distinct roles/personas (research → draft → review, extract → compare → summarize) or custom role prompts you want to reuse → an agent team.
