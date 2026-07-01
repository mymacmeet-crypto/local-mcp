# local-mcp

`local-mcp` is a small Python MCP server with tools for SearXNG web search, extracting site URLs, extracting page content, and extracting text from images.

The tool follows this flow:

```text
robots.txt
  -> find sitemap URLs
  -> parse sitemap XML
  -> collect URLs
  -> fetch page
  -> httpx
  -> content found?
     -> yes: extract URLs
     -> no: crawl4ai fallback
```

## Setup

Requires Python 3.10+.

The `extract_image_text` tool also requires the native Tesseract OCR executable:

- Windows: install Tesseract OCR. The tool auto-detects the standard `C:\Program Files\Tesseract-OCR\tesseract.exe` install path; set `TESSERACT_CMD` if it is installed elsewhere.
- macOS/Linux: install `tesseract` with your system package manager.

```bash
cd local-mcp
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
crawl4ai-setup
```

## Run

```bash
python server.py
python server.py --http
```

HTTP mode listens on `127.0.0.1:3002` by default.

## SearXNG search

Run SearXNG locally and enable JSON output in its `settings.yml`:

```yaml
search:
  formats:
    - html
    - json
```

Then point this MCP server at it:

```bash
export SEARXNG_BASE_URL=http://127.0.0.1:8080
```

For failover, set a comma-separated list:

```bash
export SEARXNG_URLS=http://127.0.0.1:8080,https://your-backup-searxng.example
```

`LOCAL_MCP_SEARXNG_URLS` is also supported as an alias. Individual `web_search` calls can override the base URL with the `searxng_url` parameter.

## Claude Desktop config

```json
{
  "mcpServers": {
    "local-mcp": {
      "command": "D:\\MCP\\local-mcp\\.venv\\Scripts\\python.exe",
      "args": ["D:\\MCP\\local-mcp\\server.py"]
    }
  }
}
```

## Tools

### `web_search`

Parameters:

- `query`: search query to send to SearXNG.
- `limit`: maximum number of search results to return. Default: `8`.
- `categories`: SearXNG categories, for example `general`, `news`, `images`, or `general,news`. Default: `general`.
- `language`: SearXNG language code. Default: `auto`.
- `pageno`: SearXNG result page number. Default: `1`.
- `safesearch`: safe-search level, where `0` is off, `1` is moderate, and `2` is strict. Default: `0`.
- `time_range`: optional SearXNG time range: `day`, `month`, or `year`.
- `engines`: optional comma-separated SearXNG engines override.
- `searxng_url`: optional SearXNG base URL for this request.

The response is citation-ready Markdown with linked result titles, source URLs, snippets, engines, answers, and suggestions when SearXNG returns them.

### `extract_urls`

Parameters:

- `url`: page or site URL.
- `same_domain`: only return URLs on the input hostname. Default: `true`.
- `same_path`: only return URLs under the input URL path prefix, for example `https://example.com/blogs` returns `/blogs` and `/blogs/...` URLs. Default: `true`.
- `limit`: maximum unique URLs to return. Default: `500`.

The response includes URL stats by source, then a Markdown bullet list of absolute URLs with the source that found each URL, such as `robots.txt`, `sitemap.xml`, `httpx`, or `Crawl4AI`. If no URLs are found, the tool returns the stats and a short message.

### `extract_content`

Parameters:

- `url`: page URL to extract. Scheme-less input like `example.com` is allowed.
- `include_title`: prepend the page title as a top-level Markdown heading. Default: `true`.

Fetches the page with httpx and converts the readable HTML to Markdown (scripts, styles, and other non-content tags are stripped; relative links and images are resolved to absolute URLs). When the static HTML yields little content — for example a JavaScript-rendered page — it falls back to `crawl4ai` browser rendering and uses its native Markdown output. The response is the Markdown content.

### `extract_image_text`

Parameters:

- `image`: image file path, image URL, data URL, or base64-encoded image content.
- `lang`: Tesseract language code. Default: `eng`.

The response is only the text recognized from the image.
