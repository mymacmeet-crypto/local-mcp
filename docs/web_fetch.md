# `web_fetch`

## Overview

`web_fetch` is the **evidence** stage of web research. It fetches, browser-renders, or scrapes a page and returns a JSON envelope whose `content` field holds the extracted page content (Markdown, plain text, or HTML), alongside a server-generated `summary` and `key_points`.

Key capabilities:

- Accepts full URLs or scheme-less input such as `example.com`.
- Uses `httpx` for fast static fetches.
- Can force browser rendering through the optional Crawl4AI backend.
- In `auto` mode, falls back to browser rendering when static Markdown or text is too thin.
- Supports CSS selectors for region-level scraping.
- Can include page metadata, links, and image URLs.
- Resolves relative links and image URLs to absolute URLs.
- Generates a concise extractive `summary` and `key_points` server-side, and frames the response as intermediate evidence (`display_policy: internal_working_material`) with an `agent_guidance` string that instructs the model to analyze the content and write its own cited answer rather than pasting the raw content to the user.

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
| `render` | string | `auto` | `auto`, `static`, or `browser`. |
| `output_format` | string | `markdown` | `markdown`, `text`, `html`, or `json`. |
| `selector` | string | empty | Optional CSS selector for scraping a specific region. |
| `include_links` | boolean | `false` | Add a `links` array (each `{url, text}`) to the response. |
| `include_images` | boolean | `false` | Add an `images` array (each `{url, alt, title, ...}`) to the response. |
| `include_metadata` | boolean | `true` | Populate the `metadata` block in the response. When `false`, `metadata` is an empty object. |
| `output_format` | string | `markdown` | Format of the `content` field: `markdown`, `text`, `html`, or `json` (`json` yields Markdown `content`). |
| `max_chars` | integer | `120000` | Maximum `content` characters before truncation. Use `0` for no truncation. |

Example MCP prompts:

```text
Using local-mcp, fetch https://example.com as Markdown.
```

```text
Using local-mcp, browser-render https://example.com/app and return text.
```

```text
Using local-mcp, scrape .product-card elements from https://example.com/catalog and return JSON with links and images.
```

Example OpenWebUI-style call:

```python
await tools.web_fetch(
    url="https://example.com/catalog",
    render="auto",
    output_format="json",
    selector=".product-card",
)
```

## Output

Every `web_fetch` call returns a JSON evidence envelope. The `content` field holds the extracted page content in the requested `content_format`; `summary` and `key_points` are generated server-side; `agent_guidance`, `requires_analysis`, and `display_policy` frame the payload as intermediate working material.

```json
{
  "tool": "web_fetch",
  "stage": "evidence",
  "url": "https://example.com",
  "final_url": "https://example.com/",
  "status": 200,
  "title": "Example Domain",
  "render_method": "httpx",
  "content_format": "markdown",
  "selector": "",
  "requires_analysis": true,
  "display_policy": "internal_working_material",
  "workflow": "web_search (discover sources) -> web_fetch (read evidence) -> analyze -> write a cited answer",
  "agent_guidance": "This is source material (evidence) ... do NOT paste it ... write your own concise answer that cites this url.",
  "next_action": "Analyze content (and summary/key_points) as evidence, then write a synthesized answer citing this url.",
  "summary": "A short extractive summary of the page.",
  "key_points": ["Key sentence one.", "Key sentence two."],
  "metadata": {"title": "Example Domain"},
  "warnings": [],
  "truncated": false,
  "content": "# Example Domain\n\nThis domain is for use in illustrative examples in documents."
}
```

`links` and `images` arrays are added only when `include_links` / `include_images` are `true`. Setting `include_metadata=false` returns an empty `metadata` object.

## Configuration

Supported environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `LOCAL_MCP_TIMEOUT_MS` | `15000` | Timeout for static page fetches and Crawl4AI runs. |
| `LOCAL_MCP_USER_AGENT` | `local-mcp/1.0 (+https://github.com/your-org/local-mcp)` | User-Agent sent to target websites. |
| `LOCAL_MCP_MIN_MARKDOWN_CHARS` | `200` | Static Markdown/text length below which `auto` mode attempts browser fallback. |
| `LOCAL_MCP_WEB_FETCH_LINK_LIMIT` | `100` | Maximum links included by `web_fetch`. |
| `LOCAL_MCP_WEB_FETCH_IMAGE_LIMIT` | `100` | Maximum images included by `web_fetch`. |

## Troubleshooting

### Browser rendering is unavailable

Install the optional browser dependency and browser assets:

```powershell
python -m pip install ".[browser]"
crawl4ai-setup
```

### Selector returns no content

Confirm the selector matches the fetched or browser-rendered HTML. For JavaScript-heavy pages, use `render="browser"` or `render="auto"`.

### Output is too large

Lower `max_chars`, use `selector` to target a smaller region, or rely on the response `summary` and `key_points` instead of the full `content` field.

## References

- Project implementation: [`local_mcp/tools/web.py`](../local_mcp/tools/web.py), [`local_mcp/web/html.py`](../local_mcp/web/html.py), [`local_mcp/web/fetcher.py`](../local_mcp/web/fetcher.py)
- Crawl4AI documentation: <https://docs.crawl4ai.com/>
- Beautiful Soup documentation: <https://beautiful-soup-4.readthedocs.io/en/latest/>
- HTTPX documentation: <https://www.python-httpx.org/>
