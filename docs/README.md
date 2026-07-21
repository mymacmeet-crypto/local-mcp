# local-mcp Tool Documentation

This folder documents every tool exposed by the `local-mcp` MCP server.

`local-mcp` is a Python MCP server that helps AI clients search the web, get one-shot LLM-powered answers (local Ollama by default, or Google Gemini), fetch/browser-render/scrape pages, discover URLs, run OCR on images, parse PDFs/documents, generate local Markdown, text, PDF, Word, or PowerPoint files (from supplied content or from web research), and create scheduled local automations. The tools are registered in [`local_mcp/app.py`](../local_mcp/app.py) with FastMCP and can also be used from OpenWebUI through [`integrations/openwebui_tool.py`](../integrations/openwebui_tool.py).

For the package structure and runtime flow, see [`ARCHITECTURE.md`](ARCHITECTURE.md).

For Qwen and other smaller local models, see [`low_model_compatibility.md`](low_model_compatibility.md).

## Tool Index

| Tool | Documentation | Main purpose |
| --- | --- | --- |
| `web_search` | [web_search.md](web_search.md) | Search through a SearXNG instance and return citation-ready Markdown results. |
| `smart_search` | [smart_search.md](smart_search.md) | One-shot answer: search, let an LLM (local Ollama by default) rank sources, crawl them, and return an LLM-written cited summary. |
| `web_fetch` | [web_fetch.md](web_fetch.md) | Fetch one page (with automatic browser fallback) and return its Markdown content as evidence. |
| `extract_urls` | [extract_urls.md](extract_urls.md) | Discover URLs from `robots.txt`, XML sitemaps, static HTML links, and optional browser-rendered pages. |
| `extract_image_text` | [extract_image_text.md](extract_image_text.md) | Extract text from local, remote, data URL, or base64 image input using Tesseract OCR. |
| `parse_document` | [parse_document.md](parse_document.md) | Parse PDFs and documents into Markdown, text, or JSON using local parser backends. |
| `generate_file` | [generate_file.md](generate_file.md) | Generate local md/txt/pdf/docx/pptx files from supplied content or from a researched web query (`smart_search`/`deep_research`). |
| `schedule_task` | [schedule_task.md](schedule_task.md) | Create and install cron, systemd, launchd, or n8n schedules for recurring local commands (plus `list_scheduled_tasks`/`delete_scheduled_task`). |

## Shared Project Setup

All tools use the same Python project setup:

```powershell
python setup_and_run.py
```

The setup script shows its command menu before installing anything. Choose option `3` for core dependencies, option `9` for the recommended bundle, option `10` for installed tool status, or option `12` to restart the local SearXNG Docker container on `http://127.0.0.1:8888`.

Manual setup:

```powershell
cd D:\MCP\local-mcp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Install the optional browser-render fallback when you want JavaScript-rendered content support:

```powershell
python -m pip install ".[browser]"
crawl4ai-setup
```

Install optional document parser engines when you need more than the default lightweight PDF text extraction:

```powershell
python -m pip install ".[document-fast]"        # PyMuPDF4LLM + pdfplumber
python -m pip install ".[document-structured]"  # Docling
python -m pip install ".[document-deep-marker]" # Marker
python -m pip install ".[document-deep-mineru]" # MinerU
```

`document-deep-marker` and `document-deep-mineru` cannot be installed together in the
same environment: `marker-pdf` requires `Pillow<11` while `mineru` requires `Pillow>=11`.
Pick whichever backend you need.

Start the MCP server over stdio for desktop MCP clients:

```powershell
python -m local_mcp
```

Start the MCP server over Streamable HTTP for OpenWebUI or direct HTTP clients:

```powershell
python -m local_mcp --http
```

HTTP mode listens on `http://127.0.0.1:3002/mcp` by default. The health endpoint is:

```powershell
Invoke-WebRequest http://127.0.0.1:3002/health
```

## Shared Environment Variables

| Variable | Default | Used by | Description |
| --- | --- | --- | --- |
| `MCP_TRANSPORT` | `stdio` | Server | Set to `http` or `stdio` when no command-line transport flag is supplied. |
| `MCP_HTTP_HOST` | `127.0.0.1` | Server | Host used in HTTP mode. |
| `MCP_HTTP_PORT` | `3002` | Server | Port used in HTTP mode. |
| `LOCAL_MCP_TIMEOUT_MS` | `15000` | Fetching, OCR URL fetches, browser render | Request and browser-render timeout in milliseconds. |
| `LOCAL_MCP_USER_AGENT` | `local-mcp/1.0 (+https://github.com/your-org/local-mcp)` | Fetching | User-Agent sent to websites and image URLs. |
| `LOCAL_MCP_URL_LIMIT` | `500` | `extract_urls` | Default maximum number of URLs returned. |
| `LOCAL_MCP_MIN_MARKDOWN_CHARS` | `200` | `web_fetch`, `smart_search` | Minimum static Markdown length before browser-render fallback is attempted. |
| `LOCAL_MCP_TOOL_PROFILE` | `full` | Tool registration | Set to `simple` for smaller models, `full` for the original tools, or `both` to expose both sets. |
| `SEARXNG_BASE_URL` | `http://127.0.0.1:8888` | `web_search` | Default SearXNG base URL. |
| `SEARXNG_URLS` | unset | `web_search` | Comma-separated SearXNG failover list. |
| `LOCAL_MCP_SEARXNG_URLS` | unset | `web_search` | Alias for `SEARXNG_URLS`. |
| `SEARXNG_TIMEOUT_MS` | `LOCAL_MCP_TIMEOUT_MS` or `15000` | `web_search`, `smart_search` | SearXNG request timeout in milliseconds. |
| `LLM_PROVIDER` | `ollama` | `smart_search` | LLM backend for ranking/summarization: `ollama` (local, default) or `gemini`. |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | `smart_search` | Local Ollama server base URL. Used when `LLM_PROVIDER=ollama`. |
| `OLLAMA_MODEL` | `qwen2.5:7b` | `smart_search` | Ollama model tag used for ranking and summarization. Must already be pulled. |
| `OLLAMA_TIMEOUT_MS` | `120000` | `smart_search` | Per-request timeout for Ollama calls in milliseconds. |
| `OLLAMA_MAX_RETRIES` | `2` | `smart_search` | Retries for transient Ollama `5xx` errors. |
| `OLLAMA_RETRY_BACKOFF_S` | `2` | `smart_search` | Base backoff in seconds between Ollama retries (grows per attempt). |
| `GEMINI_API_KEY` | required if `LLM_PROVIDER=gemini` | `smart_search` | Google Gemini API key. `GOOGLE_API_KEY` is accepted as an alias. |
| `GEMINI_MODEL` | `gemini-flash-latest` | `smart_search` | Gemini model id used for source ranking and summarization. |
| `GEMINI_API_BASE` | `https://generativelanguage.googleapis.com/v1beta` | `smart_search` | Gemini REST API base URL. |
| `GEMINI_TIMEOUT_MS` | `120000` | `smart_search` | Per-request timeout for Gemini calls in milliseconds. |
| `GEMINI_MAX_RETRIES` | `2` | `smart_search` | Retries for transient Gemini `5xx` errors (auth/quota/model errors are not retried). |
| `GEMINI_RETRY_BACKOFF_S` | `2` | `smart_search` | Base backoff in seconds between Gemini retries (grows per attempt). |
| `LOCAL_MCP_SMART_SEARCH_CANDIDATES` | `4` | `smart_search` | Candidate multiplier: search pulls `max_sources` × this many URLs (clamped 6–20) for ranking. |
| `LOCAL_MCP_SMART_SEARCH_SOURCE_CHARS` | `16000` | `smart_search` | Maximum characters of each crawled page passed to the LLM. |
| `TESSERACT_CMD` | auto-detected | `extract_image_text` | Path to the native Tesseract executable. |
| `LOCAL_MCP_OCR_MAX_IMAGE_BYTES` | `20971520` | `extract_image_text` | Maximum accepted image size in bytes. |
| `LOCAL_MCP_TESSERACT_CONFIG` | empty | `extract_image_text` | Extra config string passed to Tesseract. |
| `LOCAL_MCP_DOCUMENT_MAX_BYTES` | `104857600` | `parse_document` | Maximum accepted local, remote, or base64 document size in bytes. |
| `LOCAL_MCP_DOCUMENT_PARSER_TIMEOUT_S` | `900` | `parse_document` | Timeout for Marker and MinerU CLI parsers. |
| `LOCAL_MCP_DOCUMENT_TMPDIR` | `.tmp/documents` | `parse_document` | Directory for downloaded/base64 documents and parser output temp files. |
| `LOCAL_MCP_MARKER_CMD` | auto-detected | `parse_document` | Optional path to the `marker_single` executable. |
| `LOCAL_MCP_MINERU_CMD` | auto-detected | `parse_document` | Optional path to the `mineru` executable. |
| `LOCAL_MCP_MINERU_BACKEND` | `pipeline` | `parse_document` | MinerU backend passed with `-b`; `pipeline` is CPU-friendly. |
| `LOCAL_MCP_FILE_OUTPUT_DIR` | required | `generate_file` | Destination folder for generated files. |
| `LOCAL_MCP_DOWNLOAD_DIR` | optional alias | `generate_file` | Used only when `LOCAL_MCP_FILE_OUTPUT_DIR` is empty. If neither is set, file-writing tools return an error. |
| `LOCAL_MCP_AUTOMATION_DIR` | `.tmp/automations` or file output dir | `schedule_task` | Destination folder for generated automation bundles. |
| `LOCAL_MCP_ENABLE_SCHEDULER_INSTALL` | unset (installs allowed) | `schedule_task` | Set to `0` to disallow automatic cron/systemd/launchd changes. |

## MCP Client Example

For Claude Desktop or another stdio MCP client, configure this repository's Python executable and package entrypoint:

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

For OpenWebUI, run the server in HTTP mode and paste the contents of [`integrations/openwebui_tool.py`](../integrations/openwebui_tool.py) into OpenWebUI's tool editor. The bridge forwards OpenWebUI tool calls to `http://localhost:3002/mcp` and exposes all eight tools (`web_search`, `web_fetch`, `extract_urls`, `smart_search`, `deep_research`, `extract_image_text`, `parse_document`, `generate_file`).

Each bridged call sends an MCP progress token and streams the tool's `notifications/progress` messages to OpenWebUI as live status updates, so long-running tools (`deep_research`, `smart_search`, `generate_file`) show real-time progress instead of a frozen spinner. Synthesized answers are echoed into the chat; raw source material (`web_fetch`, `extract_urls`, `parse_document` output, and the `web_search` URL list) is returned to the model only, not dumped into the chat.
