# local-mcp Architecture

`local-mcp` is a Python MCP server that exposes tools for web search, one-shot LLM-powered answers (local Ollama by default, or Google Gemini), web fetch/scraping, URL discovery, OCR, document parsing, and file generation.

## Runtime Entry Points

- `local_mcp/app.py`: creates the `FastMCP` app, registers tools, adds the health route, and exposes the ASGI `app`.
- `local_mcp/cli.py`: selects stdio or Streamable HTTP transport.
- `local_mcp/__main__.py`: enables `python -m local_mcp`.
- `setup_and_run.py`: opens a terminal menu for setup, dependency installation, status checks, tests, and server run commands.
- `integrations/openwebui_tool.py`: OpenWebUI bridge that calls the HTTP MCP endpoint.

## Package Layout

```text
local_mcp/
  app.py                 FastMCP application setup
  cli.py                 CLI transport selection
  __main__.py            python -m local_mcp entry point
  tools/                 MCP-facing tool handlers and parameter schemas
  web/                   HTTP fetching, browser fallback, HTML parsing/scraping, sitemaps, shared fetch-to-Markdown helper (content.py)
  search/                SearXNG JSON client and result parsing
  llm/                   Provider-agnostic dispatch (LLM_PROVIDER) between ollama/ and gemini/
  ollama/                Local Ollama chat API client (default backend for smart_search)
  gemini/                Google Gemini REST client (optional smart_search backend)
  ocr/                   Tesseract image OCR implementation
  documents/             Document loading, parser backends, formatting
  file_generation/       Local file generation helpers
  shared/                URL, file-source, and tool-error helpers

integrations/
  openwebui_tool.py      OpenWebUI tool bridge

tests/
  test_*.py              Standard-library unittest coverage
```

Implementation code lives under `local_mcp/`. Root files are limited to project metadata, setup helpers, and documentation.

## Tool Flow

### `web_fetch`

```text
MCP client
  -> local_mcp.tools.web.web_fetch
  -> normalize input URL
  -> httpx static fetch with automatic Crawl4AI browser fallback when content is thin
  -> local_mcp.web.html extracts Markdown content
  -> truncate to max_chars
  -> minimal JSON evidence envelope (url, content, requires_analysis, agent_guidance)
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

### `web_search`

```text
MCP client
  -> local_mcp.tools.search.web_search
  -> local_mcp.search.searxng calls /search?format=json
  -> result cleanup, de-duplication, limit handling
  -> collect result URLs in SearXNG order
  -> minimal JSON discovery envelope (urls, requires_fetch, agent_guidance)
```

### `smart_search`

```text
MCP client
  -> local_mcp.tools.smart_search.smart_search
  -> require the configured LLM provider ready (local_mcp.llm.client, LLM_PROVIDER=ollama|gemini)
  -> local_mcp.search.searxng gathers candidate URLs (max_sources x multiplier)
  -> local_mcp.llm.client ranks all candidates best-first (local_mcp.ollama.client or local_mcp.gemini.client)
  -> local_mcp.web.content.fetch_auto crawls ranked pages, skipping failures
     until max_sources pages load (httpx with Crawl4AI browser fallback)
  -> local_mcp.llm.client summarizes the crawled evidence with inline citations
  -> plain-text answer followed by a numbered Sources list
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

### `generate_file`

```text
MCP client
  -> local_mcp.tools.file_generation.generate_file
  -> local_mcp.file_generation.write_generated_file / append_generated_file validates md/pdf settings
  -> resolve filename under LOCAL_MCP_FILE_OUTPUT_DIR / LOCAL_MCP_DOWNLOAD_DIR
  -> create parent folders and write UTF-8 Markdown, append Markdown chunks, or write PDF bytes
  -> Markdown response with path and write stats
```

### `web_search_to_file`

```text
MCP client
  -> local_mcp.tools.file_generation.web_search_to_file
  -> local_mcp.search.searxng.search returns results, answers, and suggestions
  -> local_mcp.tools.search.format_search_response formats citation-ready Markdown
  -> local_mcp.file_generation.write_generated_file / append_generated_file persists Markdown or PDF output
  -> Markdown response with search count, path, and write stats
```

## Dependency Model

- Core runtime dependencies live in `requirements.txt` and `[project].dependencies`.
- Optional browser rendering is installed with `local-mcp[browser]`.
- Optional document parser tiers are installed with:
  - `local-mcp[document-fast]`
  - `local-mcp[document-structured]`
  - `local-mcp[document-deep-marker]` (Marker; requires `Pillow<11`)
  - `local-mcp[document-deep-mineru]` (MinerU; requires `Pillow>=11`, conflicts with Marker's Pillow pin)
- Native Tesseract is still required outside Python for `extract_image_text`.

## Run Modes

```powershell
python setup_and_run.py
python -m local_mcp
python -m local_mcp --http
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
.venv\Scripts\python.exe -c "import local_mcp.app; import local_mcp.cli; print('ok')"
```
