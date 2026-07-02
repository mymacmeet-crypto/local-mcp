# local-mcp

`local-mcp` is a small Python MCP server with tools for SearXNG web search, extracting site URLs, extracting page content, extracting text from images, parsing PDFs/documents, and generating local Markdown files.

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

For an interactive setup that creates `.venv`, installs the core runtime, and then offers run options:

```bash
python setup_and_run.py
```

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
pip install ".[document-deep]"        # Marker + MinerU
```

## Run

```bash
python server.py
python server.py --http
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

- `filename`: output Markdown filename or relative path. The `.md` extension is appended when omitted.
- `content`: Markdown content to write.
- `file_type`: output type. MVP supports only `md`/`markdown`. Default: `md`.
- `output_dir`: destination directory. Empty uses `LOCAL_MCP_FILE_OUTPUT_DIR`, `LOCAL_MCP_DOWNLOAD_DIR`, or `generated_files`.
- `overwrite`: replace an existing file at the target path. Default: `false`.
- `ensure_trailing_newline`: append a trailing newline to non-empty content. Default: `true`.

The response reports the generated file path, byte count, character count, and whether an existing file was overwritten. Future formats can be added behind the same tool; the current MVP intentionally writes only Markdown.

To choose a default download location without passing `output_dir` every time, set it in `.env`:

```env
LOCAL_MCP_FILE_OUTPUT_DIR=D:\MCP\local-mcp\generated_files
```
