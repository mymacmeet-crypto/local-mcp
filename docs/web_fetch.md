# `web_fetch`

## Overview

`web_fetch` is the **evidence** stage of web research. It fetches one page and returns a minimal JSON envelope whose `content` field holds the extracted page content as Markdown.

Key capabilities:

- Accepts full URLs or scheme-less input such as `example.com`.
- Uses `httpx` for fast static fetches.
- Automatically falls back to browser rendering (via the optional Crawl4AI backend) when the static Markdown is too thin.
- Resolves relative links and image URLs to absolute URLs in the extracted Markdown.
- Frames the response as intermediate evidence with `requires_analysis: true` and an `agent_guidance`/`next_action` pair that instructs the model to analyze the content and write its own cited answer rather than pasting the raw content to the user.

## Installation

Install core dependencies:

```powershell
python -m pip install -r requirements.txt
```

Install optional browser-render support:

```powershell
python -m pip install ".[browser]"
crawl4ai-setup
```

## Usage

The tool accepts these parameters:

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `url` | string | required | Page URL. Scheme-less input such as `example.com` is allowed. |
| `max_chars` | integer | `120000` | Maximum `content` characters before truncation. Use `0` for no truncation. |

Example MCP prompts:

```text
Using local-mcp, fetch https://example.com and use the content as evidence.
```

```text
Using local-mcp, fetch https://example.com/app with max_chars=20000.
```

Example OpenWebUI-style call:

```python
await tools.web_fetch(
    url="https://example.com",
    max_chars=20000,
)
```

## Output

Every `web_fetch` call returns a minimal JSON evidence envelope. The `content` field holds the extracted page content as Markdown; `agent_guidance`, `next_action`, and `requires_analysis` frame the payload as intermediate working material.

```json
{
  "stage": "evidence",
  "url": "https://example.com",
  "requires_analysis": true,
  "workflow": "web_search (discover sources) -> web_fetch (read evidence) -> analyze -> write a cited answer",
  "agent_guidance": "This is source material (evidence) ... do NOT paste it ... write your own concise answer that cites this url.",
  "next_action": "Analyze content as evidence, then write a synthesized answer citing this url.",
  "content": "# Example Domain\n\nThis domain is for use in illustrative examples in documents."
}
```

When `max_chars` truncates the page, `content` is cut to that length. When nothing can be extracted, the call returns an error rather than an empty envelope.

## Configuration

Supported environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `LOCAL_MCP_TIMEOUT_MS` | `15000` | Timeout for static page fetches and Crawl4AI runs. |
| `LOCAL_MCP_USER_AGENT` | `local-mcp/1.0 (+https://github.com/your-org/local-mcp)` | User-Agent sent to target websites. |
| `LOCAL_MCP_MIN_MARKDOWN_CHARS` | `200` | Static Markdown length below which the fetch attempts browser fallback. |

## Troubleshooting

### Browser rendering is unavailable

Install the optional browser dependency and browser assets:

```powershell
python -m pip install ".[browser]"
crawl4ai-setup
```

`web_fetch` automatically attempts browser rendering when the static Markdown is thin, so installing this support improves results on JavaScript-heavy pages.

### Output is too large

Lower `max_chars` to cap the returned `content`.

## References

- Project implementation: [`local_mcp/tools/web.py`](../local_mcp/tools/web.py), [`local_mcp/web/html.py`](../local_mcp/web/html.py), [`local_mcp/web/fetcher.py`](../local_mcp/web/fetcher.py)
- Crawl4AI documentation: <https://docs.crawl4ai.com/>
- Beautiful Soup documentation: <https://beautiful-soup-4.readthedocs.io/en/latest/>
- HTTPX documentation: <https://www.python-httpx.org/>
