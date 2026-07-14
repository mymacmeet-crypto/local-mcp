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


# --------------------------------------------------------------------------- #
# Tool descriptions (used as MCP tool docstrings).                            #
# --------------------------------------------------------------------------- #

WEB_SEARCH_DESCRIPTION = (
    "STEP 1 of web research: DISCOVER candidate sources. This is a discovery "
    "tool, NOT an answer tool.\n\n"
    "Searches the web (SearXNG) and returns a JSON envelope with a list of "
    "candidate source `urls` and `requires_fetch: true`. The URLs alone are "
    "NOT sufficient evidence to answer a factual or research question.\n\n"
    "You MUST NOT answer the user from this list, and you MUST NOT paste it "
    "into the chat. After searching, call `web_fetch` on one or more of the "
    "`urls`, read the returned page evidence, then write your own synthesized "
    "answer with citations.\n\n"
    f"Workflow: {WORKFLOW}."
)

SMART_SEARCH_DESCRIPTION = (
    "One-shot web answer: search the web, let an LLM pick the most "
    "relevant sources, crawl them, and return an LLM-written summary that "
    "already cites its sources.\n\n"
    "Unlike `web_search` (which only DISCOVERS candidate URLs and needs a "
    "follow-up `web_fetch`), this tool runs the whole discover -> crawl -> "
    "summarize pipeline internally and returns a FINAL, synthesized answer plus "
    "the list of source URLs it used. Prefer it when you want a direct answer to "
    "a factual or research question without manually chaining tools.\n\n"
    "Uses a local Ollama model by default (LLM_PROVIDER=ollama); set "
    "LLM_PROVIDER=gemini and GEMINI_API_KEY to use Google Gemini instead. "
    "Returns plain text: the summary followed by a numbered `Sources:` list."
)

WEB_FETCH_DESCRIPTION = (
    "STEP 2 of web research: RETRIEVE the full content of one web page as "
    "evidence. Use it after `web_search` on the URLs it recommends, or on any "
    "specific URL you need to read.\n\n"
    "Returns a JSON envelope with the page `url` and its Markdown `content`. "
    "The `content` field is raw SOURCE MATERIAL for your analysis and is "
    "internal working material. Do NOT display `content`, markdown, HTML, JSON "
    "payloads, or long fetched text blocks to the user. Instead, read the "
    "evidence, extract the facts that answer the question, and write your OWN "
    "concise, synthesized answer that cites the url.\n\n"
    f"Workflow: {WORKFLOW}."
)


# --------------------------------------------------------------------------- #
# Guidance embedded in tool OUTPUTS (the `agent_guidance` fields).            #
# --------------------------------------------------------------------------- #

SEARCH_RESULT_GUIDANCE = (
    "These are candidate source URLs discovered on the web, not a final answer. "
    "Next step: call web_fetch on one or more of the `urls`, read the returned "
    "evidence, then write your own synthesized answer with citations. Do not "
    "show this JSON or the raw URL list to the user."
)

SEARCH_NEXT_ACTION = (
    "Call web_fetch on one or more of the `urls` to read the full pages, then "
    "analyze that evidence and answer. Do not answer from the URL list alone."
)

FETCH_RESULT_GUIDANCE = (
    "This is source material (evidence) fetched from one web page, not a final "
    "answer. `content` is internal working material: do NOT paste it, the "
    "markdown, HTML, or any raw text block into your reply. Read it, extract "
    "the facts that answer the user's question, and write your own concise "
    "answer that cites this url. If this page lacks the answer, fetch another "
    "URL."
)

FETCH_NEXT_ACTION = (
    "Analyze `content` as evidence, then write a synthesized answer citing this "
    "url. Fetch another source if you need more."
)
