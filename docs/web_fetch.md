# `web_fetch`

## Overview

`web_fetch` fetches, browser-renders, or scrapes a page and returns Markdown, plain text, HTML, or structured JSON.

Key capabilities:

- Accepts full URLs or scheme-less input such as `example.com`.
- Uses `httpx` for fast static fetches.
- Can force browser rendering through the optional Crawl4AI backend.
- In `auto` mode, falls back to browser rendering when static Markdown or text is too thin.
- Supports CSS selectors for region-level scraping.
- Can include page metadata, links, and image URLs.
- Resolves relative links and image URLs to absolute URLs.

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
| `include_links` | boolean | `false` | Include scraped links in non-JSON responses. JSON responses always include links. |
| `include_images` | boolean | `false` | Include scraped image URLs in non-JSON responses. JSON responses always include images. |
| `include_metadata` | boolean | `true` | Include fetch metadata before non-JSON content. JSON responses always include metadata. |
| `max_chars` | integer | `120000` | Maximum content characters before truncation. Use `0` for no truncation. |

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

Markdown, text, and HTML responses can include a metadata preface:

```text
Fetch metadata:
- URL: https://example.com
- Final URL: https://example.com/
- Status: 200
- Render method: httpx
- Output format: markdown
- Title: Example Domain

# Example Domain

This domain is for use in illustrative examples in documents.
```

JSON responses include structured fields:

```json
{
  "url": "https://example.com",
  "final_url": "https://example.com/",
  "status": 200,
  "render_method": "httpx",
  "output_format": "json",
  "selector": "",
  "metadata": {},
  "warnings": [],
  "content": "Example content",
  "links": [],
  "images": []
}
```

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

Lower `max_chars`, use `selector` to target a smaller region, or use `output_format="json"` and process only the fields you need.

## References

- Project implementation: [`local_mcp/tools/web.py`](../local_mcp/tools/web.py), [`local_mcp/web/html.py`](../local_mcp/web/html.py), [`local_mcp/web/fetcher.py`](../local_mcp/web/fetcher.py)
- Crawl4AI documentation: <https://docs.crawl4ai.com/>
- Beautiful Soup documentation: <https://beautiful-soup-4.readthedocs.io/en/latest/>
- HTTPX documentation: <https://www.python-httpx.org/>
