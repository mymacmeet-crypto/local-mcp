# local-mcp Architecture

`local-mcp` is a Python MCP server that exposes tools for web search, web fetch/scraping, URL discovery, readable content extraction, OCR, and document parsing.

## Runtime Entry Points

- `server.py`: compatibility entry point. Keeps `python server.py` and ASGI `app` imports working.
- `local_mcp/app.py`: creates the `FastMCP` app, registers tools, adds the health route, and exposes the ASGI `app`.
- `local_mcp/cli.py`: selects stdio or Streamable HTTP transport.
- `setup_and_run.py`: bootstraps `.venv`, installs dependencies, and provides a terminal menu to run the MCP server.
- `integrations/openwebui_tool.py`: OpenWebUI bridge that calls the HTTP MCP endpoint.

## Package Layout

```text
local_mcp/
  app.py                 FastMCP application setup
  cli.py                 CLI transport selection
  tools/                 MCP-facing tool handlers and parameter schemas
  web/                   HTTP fetching, browser fallback, HTML parsing/scraping, sitemaps
  search/                SearXNG JSON client and result parsing
  ocr/                   Tesseract image OCR implementation
  documents/             Document loading, parser backends, formatting
  shared/                URL, file-source, and tool-error helpers

integrations/
  openwebui_tool.py      OpenWebUI tool bridge

tests/
  test_*.py              Standard-library unittest coverage
```

Root files such as `fetcher.py`, `extract.py`, `searxng.py`, `ocr.py`, and `document_parser.py` are compatibility wrappers. New code should import from `local_mcp/...`.

## Tool Flow

### `web_fetch`

```text
MCP client
  -> local_mcp.tools.web.web_fetch
  -> normalize input URL
  -> httpx static fetch, Crawl4AI browser render, or auto fallback
  -> optional CSS selector narrowing
  -> local_mcp.web.html extracts Markdown/text/HTML, metadata, links, images
  -> Markdown, text, HTML, or JSON response
```

### `extract_urls`

```text
MCP client
  -> local_mcp.tools.web.extract_urls
  -> normalize input URL
  -> local_mcp.web.sitemap discovers robots.txt and sitemap.xml URLs
  -> local_mcp.web.fetcher fetches static HTML with httpx
  -> local_mcp.web.html extracts links
  -> optional Crawl4AI browser fallback
  -> Markdown response with source stats
```

### `extract_content`

```text
MCP client
  -> local_mcp.tools.web.extract_content
  -> httpx static fetch
  -> HTML cleanup and Markdown conversion
  -> optional Crawl4AI fallback for low-content pages
  -> Markdown response
```

### `web_search`

```text
MCP client
  -> local_mcp.tools.search.web_search
  -> local_mcp.search.searxng calls /search?format=json
  -> result cleanup, de-duplication, limit handling
  -> citation-ready Markdown response
```

### `extract_image_text`

```text
MCP client
  -> local_mcp.tools.ocr.extract_image_text
  -> local path, file URI, HTTP URL, data URL, or base64 loader
  -> Pillow image normalization
  -> pytesseract
  -> plain text response
```

### `parse_document`

```text
MCP client
  -> local_mcp.tools.documents.parse_document
  -> local_mcp.documents.source loads path, file URI, URL, data URL, or base64
  -> local_mcp.documents.parsers selects or runs parser backend
  -> local_mcp.documents.formatting applies metadata and truncation
  -> Markdown, text, or JSON response
```

## Dependency Model

- Core runtime dependencies live in `requirements.txt` and `[project].dependencies`.
- Optional browser rendering is installed with `local-mcp[browser]`.
- Optional document parser tiers are installed with:
  - `local-mcp[document-fast]`
  - `local-mcp[document-structured]`
  - `local-mcp[document-deep]`
- Native Tesseract is still required outside Python for `extract_image_text`.

## Run Modes

```powershell
python setup_and_run.py
python server.py
python server.py --http
local-mcp
local-mcp --http
```

HTTP mode defaults to:

```text
http://127.0.0.1:3002/mcp
```

Health check:

```text
http://127.0.0.1:3002/health
```

## Validation

Default validation is intentionally local and non-networked:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests
.venv\Scripts\python.exe -c "import server; import local_mcp.app; import local_mcp.cli; print('ok')"
```
