# local-mcp

`local-mcp` is a small Python MCP server with tools for SearXNG web search, fetching/browsing/scraping web pages, summarizing multiple web pages, extracting site URLs, extracting text from images, parsing PDFs/documents, generating local Markdown or PDF files, and creating scheduled automation bundles.

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

For an interactive control panel, run:

```bash
python setup_and_run.py
```

The menu is shown before any dependency installation. Use option `3` for core dependencies, option `9` for the recommended bundle, option `10` to see which optional tools and parser backends are installed, or option `12` to restart the local SearXNG Docker container on `http://127.0.0.1:8888`.

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

Optional document parser engines can be installed as needed:

```bash
pip install ".[document-fast]"        # PyMuPDF4LLM + pdfplumber
pip install ".[document-structured]"  # Docling
pip install ".[document-deep-marker]" # Marker
pip install ".[document-deep-mineru]" # MinerU
```

`document-deep-marker` and `document-deep-mineru` cannot be installed together in the
same environment: `marker-pdf` requires `Pillow<11` while `mineru` requires `Pillow>=11`.
Pick whichever backend you need.

## Run

```bash
python -m local_mcp
python -m local_mcp --http
```

HTTP mode listens on `127.0.0.1:3002` by default.

For the full package layout and request flow, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

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
export SEARXNG_BASE_URL=http://127.0.0.1:8888
```

For failover, set a comma-separated list:

```bash
export SEARXNG_URLS=http://127.0.0.1:8888,https://your-backup-searxng.example
```

`LOCAL_MCP_SEARXNG_URLS` is also supported as an alias. Individual `web_search` calls can override the base URL with the `searxng_url` parameter.

The setup menu can run the included Docker config for you. Choose option `12`, or run the same commands manually:

```powershell
docker rm -f local-searxng
docker run -d `
  --name local-searxng `
  -p 8888:8080 `
  -v "${PWD}\searxng-settings.yml:/etc/searxng/settings.yml:ro" `
  searxng/searxng:latest
```

## Claude Desktop config

```json
{
  "mcpServers": {
    "local-mcp": {
      "command": "D:\\MCP\\local-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "local_mcp"]
    }
  }
}
```

## Smaller model compatibility

Smaller local models often fail MCP calls because they see too many tools, too many optional arguments, or free-form string options where they should choose from a small set. Use the simple profile for models such as Qwen-class local models:

For the full explanation of these compatibility changes, see [`docs/low_model_compatibility.md`](docs/low_model_compatibility.md).

```env
LOCAL_MCP_TOOL_PROFILE=simple
```

The `simple` profile registers simpler wrapper tools only:

- `search_web`
- `summarize_web`
- `fetch_web_page`
- `list_page_urls`
- `read_document`
- `read_image_text`
- `write_markdown_file`
- `write_report_file`
- `search_web_to_file`
- `create_scheduled_command`
- `list_scheduled_commands`
- `remove_scheduled_command`

For PDF or Markdown reports, prefer `write_report_file`. It rejects content below its `min_words` threshold, so smaller models are forced to expand the report before a half-page PDF is written. The default is `min_words=900`, which is usually closer to a 2-3 page PDF than a short answer.

In the `simple` profile, `search_web` searches and then fetches/summarizes the top result pages automatically. This gives smaller models more content than raw search snippets.

The default profile is `full`, which keeps the original tool surface. Use `both` only for clients and models that handle larger tool lists well.

You can also set the profile directly in a desktop MCP config:

```json
{
  "mcpServers": {
    "local-mcp": {
      "command": "D:\\MCP\\local-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "local_mcp"],
      "env": {
        "LOCAL_MCP_TOOL_PROFILE": "simple"
      }
    }
  }
}
```

If you keep the full profile and want every `web_search` call to fetch after searching, set:

```env
LOCAL_MCP_WEB_SEARCH_FOLLOW_UP=summarize
LOCAL_MCP_WEB_SEARCH_FOLLOW_UP_LIMIT=3
```

Supported follow-up modes are:

- `summarize`: run a search, then fetch/summarize the top results with `web_summarize`.
- `fetch_first`: run a search, then fetch the top result with `web_fetch`.
- `none`: search results only.

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

### `web_search_to_file`

Parameters:

- `query`: search query to send to SearXNG.
- `filename`: output Markdown or PDF filename or relative path. The matching extension is appended when omitted.
- `limit`: maximum number of search results to write. Default: `8`.
- `categories`: SearXNG categories, for example `general`, `news`, `images`, or `general,news`. Default: `general`.
- `language`: SearXNG language code. Default: `auto`.
- `pageno`: SearXNG result page number. Default: `1`.
- `safesearch`: safe-search level, where `0` is off, `1` is moderate, and `2` is strict. Default: `0`.
- `time_range`: optional SearXNG time range: `day`, `month`, or `year`.
- `engines`: optional comma-separated SearXNG engines override.
- `searxng_url`: optional SearXNG base URL for this request.
- `write_mode`: `append` adds a search section to the target file, `write` creates/replaces content. Default: `append`.
- `overwrite`: replace an existing file when `write_mode` is `write`. Default: `false`.
- `ensure_trailing_newline`: append a trailing newline to the generated Markdown section. Ignored for PDF output. Default: `true`.
- `file_type`: output type. Supports `md`/`markdown` and `pdf`. A `.pdf` filename also selects PDF output. Default: `md`.

This runs the search server-side and writes the formatted results directly into the generated Markdown or PDF file, so smaller models do not need to pass large search output through a `content` argument. PDF output requires `write_mode="write"` because append/chunk mode is Markdown-only.

### `web_fetch`

Parameters:

- `url`: page URL to fetch. Scheme-less input like `example.com` is allowed.
- `render`: fetch mode: `auto`, `static`, or `browser`. Default: `auto`.
- `output_format`: returned content format: `markdown`, `text`, `html`, or `json`. Default: `markdown`.
- `selector`: optional CSS selector for scraping a specific page region.
- `include_links`: include scraped links in non-JSON responses. Default: `false`.
- `include_images`: include scraped image URLs in non-JSON responses. Default: `false`.
- `include_metadata`: include fetch metadata before non-JSON content. Default: `true`.
- `max_chars`: maximum content characters before truncation. Use `0` for no truncation. Default: `120000`.

Fetches pages with `httpx`, can force optional Crawl4AI browser rendering for JavaScript-heavy pages, and supports selector-based scraping. JSON responses include metadata, content, links, and images.

### `web_summarize`

Parameters:

- `query`: optional search query. When provided, SearXNG result URLs are fetched and summarized.
- `urls`: optional URLs to summarize. Accepts comma/newline-separated URLs, raw `web_search` Markdown, or Markdown links.
- `limit`: maximum number of URLs to fetch and summarize. Default: `5`.
- `categories`, `language`, `pageno`, `safesearch`, `time_range`, `engines`, `searxng_url`: search options used when `query` is provided.
- `render`: fetch mode for each URL: `auto`, `static`, or `browser`. Default: `auto`.
- `selector`: optional CSS selector to summarize a specific page region.
- `summary_sentences`: maximum sentences per page summary. Default: `3`.
- `max_chars_per_page`: maximum extracted page characters to consider before summarizing. Default: `30000`.
- `include_failures`: include URLs that failed to fetch in the response. Default: `true`.

This tool crawls multiple URLs and returns an overall summary plus per-source summaries with citations, final URLs, fetch status, render method, and optional search snippets. It does not return the full crawled page content.

### `extract_urls`

Parameters:

- `url`: page or site URL.
- `same_domain`: only return URLs on the input hostname. Default: `true`.
- `same_path`: only return URLs under the input URL path prefix, for example `https://example.com/blogs` returns `/blogs` and `/blogs/...` URLs. Default: `true`.
- `limit`: maximum unique URLs to return. Default: `500`.

The response includes URL stats by source, then a Markdown bullet list of absolute URLs with the source that found each URL, such as `robots.txt`, `sitemap.xml`, `httpx`, or `Crawl4AI`. If no URLs are found, the tool returns the stats and a short message.

### `extract_image_text`

Parameters:

- `image`: image file path, image URL, data URL, or base64-encoded image content.
- `lang`: Tesseract language code. Default: `eng`.

The response is only the text recognized from the image.

### `parse_document`

Parameters:

- `document`: document file path, `file://` URI, HTTP(S) URL, data URL, or base64 document content.
- `parser`: backend to use: `auto`, `pypdf`, `pymupdf4llm`, `pdfplumber`, `docling`, `marker`, `mineru`, or `text`. Default: `auto`.
- `output_format`: `markdown`, `text`, or `json`. Default: `markdown`.
- `pages`: optional 1-based page range such as `1-3,5`. Empty parses all pages.
- `include_metadata`: include parser/source metadata before Markdown or text output. Default: `true`.
- `max_chars`: maximum content characters returned before truncation. Default: `120000`.

The response is parsed document content. `auto` prefers PyMuPDF4LLM when installed for fast digital PDFs, falls back to lightweight `pypdf`, and can use optional engines for structured OCR, deep-learning parsing, CJK/scientific documents, or table coordinates.

### `generate_file`

Parameters:

- `filename`: output Markdown or PDF filename or relative path. The matching extension is appended when omitted.
- `content`: Markdown-like content to write.
- `file_type`: output type. Supports `md`/`markdown` and `pdf`. A `.pdf` filename also selects PDF output. Default: `md`.
- `overwrite`: replace an existing file at the target path. Default: `false`.
- `write_mode`: `write` creates/replaces content, `append` adds the content as a chunk. Default: `write`.
- `ensure_trailing_newline`: append a trailing newline to non-empty Markdown content. Ignored for PDF output. Default: `true`.
- `min_words`: minimum word count required before writing. Use `700`-`1200` for 2-3 page reports, or `0` for short notes. Default: `0`.

The response reports the generated file path, write mode, byte count, character count, and whether an existing file was overwritten. PDF output is generated from Markdown-like text. `append`/chunk mode is supported for Markdown only; generate PDFs with `write_mode="write"` and the complete content.

For large files, call `generate_file` once with `write_mode="write"` for the first chunk, then call it again with `write_mode="append"` for later chunks.

You must define a download location in `.env`; otherwise file-writing tools return `Download path not defined`.

```env
LOCAL_MCP_FILE_OUTPUT_DIR=D:\Downloads\local-mcp
```

### `schedule_task`

Parameters:

- `name`: human-readable task name. Used to create a safe bundle slug.
- `command`: shell command or script body to run on the schedule.
- `schedule`: five-field cron expression, or alias: `hourly`, `daily`, `weekdays`, `weekly`, `monthly`.
- `scheduler`: scheduler to use: `auto`, `cron`, `launchd`, `systemd`, or `n8n`. Default: `auto` (cron when `crontab` exists, otherwise systemd user timers on Linux or launchd on macOS).
- `description`: optional task description written into the generated README.
- `working_directory`: optional working directory for the generated runner script.
- `environment`: optional `KEY=VALUE` assignments, newline or comma separated.
- `overwrite`: replace existing generated files for this task. Default: `false`.
- `install`: install the schedule after generating files. Default: `true`. Set `LOCAL_MCP_ENABLE_SCHEDULER_INSTALL=0` to disallow installs and only generate reviewable files. n8n is always manual import.

The tool writes a reviewable automation bundle with `run.sh`, scheduler-specific artifacts, logs directory, and README, then installs the schedule (crontab entry, systemd user timer on Linux, or launchd agent on macOS). It uses `LOCAL_MCP_AUTOMATION_DIR` when set, otherwise falls back to the configured file output directory and then `.tmp/automations`. The response states clearly whether the schedule is live; when it is not (install disabled, missing `crontab`, n8n), it explains why and includes the manual step.

Companion tools:

- `list_scheduled_tasks`: list generated tasks and whether each is installed.
- `delete_scheduled_task(name, delete_files=true)`: uninstall a task and optionally delete its bundle files.

Example:

```text
Using local-mcp, create a cron scheduled task named Morning report that runs "python scripts/morning_report.py" daily in /home/nayan/Documents/local-mcp.
```
