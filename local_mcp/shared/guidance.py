"""Central agent-guidance text for the web research workflow.

Search results are *discovery* data, fetched pages are *evidence*, and the
final answer must be the model's own synthesis of that evidence. These strings
are embedded both in tool descriptions (docstrings) and in tool *outputs* so
that open-source reasoning models (Qwen, DeepSeek, Llama, Mistral) are steered
consistently through the same loop instead of stopping after a search.

    User query -> web_search (discover) -> web_fetch (read evidence)
                -> analyze -> write a synthesized, cited answer
"""

from __future__ import annotations

# Short, repeatable one-liner injected into every tool description and output.
WORKFLOW = "web_search (discover sources) -> web_fetch (read evidence) -> analyze -> write a cited answer"

# Marker attached to fetched content so downstream code and models both treat
# it as intermediate material rather than a finished response.
DISPLAY_POLICY = "internal_working_material"


# --------------------------------------------------------------------------- #
# Tool descriptions (used as MCP tool docstrings).                            #
# --------------------------------------------------------------------------- #

WEB_SEARCH_DESCRIPTION = (
    "STEP 1 of web research: DISCOVER candidate sources. This is a discovery "
    "tool, NOT an answer tool.\n\n"
    "Searches the web (SearXNG) and returns ranked candidates as JSON: each "
    "result has {title, url, snippet, relevance_score}, plus `recommended_urls` "
    "and `requires_fetch: true`. The snippets are short previews only and are "
    "NOT sufficient evidence to answer a factual or research question.\n\n"
    "You MUST NOT answer the user from these search results, and you MUST NOT "
    "paste them into the chat. After searching, call `web_fetch` on one or more "
    "`recommended_urls`, read the returned page evidence, then write your own "
    "synthesized answer with citations.\n\n"
    f"Workflow: {WORKFLOW}."
)

WEB_FETCH_DESCRIPTION = (
    "STEP 2 of web research: RETRIEVE the full content of one web page as "
    "evidence. Use it after `web_search` on the URLs it recommends, or on any "
    "specific URL you need to read.\n\n"
    "Returns JSON: {url, title, summary, key_points, content, ...}. The "
    "`content` field is raw SOURCE MATERIAL for your analysis and is internal "
    "working material. Do NOT display `content`, `summary`, markdown, HTML, "
    "JSON payloads, or long fetched text blocks to the user. Instead, read the "
    "evidence, extract the facts that answer the question, and write your OWN "
    "concise, synthesized answer that cites the url.\n\n"
    f"Workflow: {WORKFLOW}."
)


# --------------------------------------------------------------------------- #
# Guidance embedded in tool OUTPUTS (the `agent_guidance` fields).            #
# --------------------------------------------------------------------------- #

SEARCH_RESULT_GUIDANCE = (
    "These are candidate sources discovered on the web, not a final answer. "
    "The snippets are previews only and are not sufficient evidence. Next step: "
    "call web_fetch on the URLs in `recommended_urls`, read the returned "
    "evidence, then write your own synthesized answer with citations. Do not "
    "show this JSON or the raw snippets to the user."
)

SEARCH_NEXT_ACTION = (
    "Call web_fetch on one or more `recommended_urls` to read the full pages, "
    "then analyze that evidence and answer. Do not answer from snippets alone."
)

FETCH_RESULT_GUIDANCE = (
    "This is source material (evidence) fetched from one web page, not a final "
    "answer. `content` is internal working material: do NOT paste it, the "
    "summary, key_points, markdown, HTML, or any raw text block into your "
    "reply. Read it, extract the facts that answer the user's question, and "
    "write your own concise answer that cites this url. If this page lacks the "
    "answer, fetch another recommended URL."
)

FETCH_NEXT_ACTION = (
    "Analyze `content` (and `summary`/`key_points`) as evidence, then write a "
    "synthesized answer citing this url. Fetch another source if you need more."
)

PREFETCHED_GUIDANCE = (
    "The server already fetched the top source(s) for you (see "
    "`prefetched_sources`), so `requires_fetch` is false. Analyze that evidence "
    "and answer the user directly with citations; you usually do not need "
    "another web_fetch call. Never paste the fetched content, summaries, "
    "key_points, or snippets into your reply, write your own synthesized answer."
)

PREFETCHED_NEXT_ACTION = (
    "Analyze `prefetched_sources` as evidence and write a synthesized, cited "
    "answer. Only call web_fetch again if that evidence is insufficient."
)
