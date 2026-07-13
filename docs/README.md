# local-mcp Tool Documentation

This folder documents every tool exposed by the `local-mcp` MCP server.

`local-mcp` is a Python MCP server that helps AI clients search the web, fetch/browser-render/scrape pages, discover URLs, run OCR on images, parse PDFs/documents, and generate local Markdown or PDF files. The tools are registered in [`local_mcp/app.py`](../local_mcp/app.py) with FastMCP and can also be used from OpenWebUI through [`integrations/openwebui_tool.py`](../integrations/openwebui_tool.py).

For the package structure and runtime flow, see [`ARCHITECTURE.md`](ARCHITECTURE.md).

For Qwen and other smaller local models, see [`low_model_compatibility.md`](low_model_compatibility.md).

## Tool Index

| Tool | Documentation | Main purpose |
| --- | --- | --- |
| `web_search` | [web_search.md](web_search.md) | Search through a SearXNG instance and return citation-ready Markdown results. |
| `web_search_to_file` | [web_search_to_file.md](web_search_to_file.md) | Search through SearXNG and write citation-ready results directly to a generated Markdown or PDF file. |
| `web_fetch` | [web_fetch.md](web_fetch.md) | Fetch one page (with automatic browser fallback) and return its Markdown content as evidence. |
| `extract_urls` | [extract_urls.md](extract_urls.md) | Discover URLs from `robots.txt`, XML sitemaps, static HTML links, and optional browser-rendered pages. |
| `extract_image_text` | [extract_image_text.md](extract_image_text.md) | Extract text from local, remote, data URL, or base64 image input using Tesseract OCR. |
| `parse_document` | [parse_document.md](parse_document.md) | Parse PDFs and documents into Markdown, text, or JSON using local parser backends. |
| `generate_file` | [generate_file.md](generate_file.md) | Generate local Markdown or PDF files from supplied content. |

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
| `LOCAL_MCP_MIN_MARKDOWN_CHARS` | `200` | `web_fetch` | Minimum static Markdown length before browser-render fallback is attempted. |
| `LOCAL_MCP_TOOL_PROFILE` | `full` | Tool registration | Set to `simple` for smaller models, `full` for the original tools, or `both` to expose both sets. |
| `SEARXNG_BASE_URL` | `http://127.0.0.1:8888` | `web_search`, `web_search_to_file` | Default SearXNG base URL. |
| `SEARXNG_URLS` | unset | `web_search`, `web_search_to_file` | Comma-separated SearXNG failover list. |
| `LOCAL_MCP_SEARXNG_URLS` | unset | `web_search`, `web_search_to_file` | Alias for `SEARXNG_URLS`. |
| `SEARXNG_TIMEOUT_MS` | `LOCAL_MCP_TIMEOUT_MS` or `15000` | `web_search`, `web_search_to_file` | SearXNG request timeout in milliseconds. |
| `TESSERACT_CMD` | auto-detected | `extract_image_text` | Path to the native Tesseract executable. |
| `LOCAL_MCP_OCR_MAX_IMAGE_BYTES` | `20971520` | `extract_image_text` | Maximum accepted image size in bytes. |
| `LOCAL_MCP_TESSERACT_CONFIG` | empty | `extract_image_text` | Extra config string passed to Tesseract. |
| `LOCAL_MCP_DOCUMENT_MAX_BYTES` | `104857600` | `parse_document` | Maximum accepted local, remote, or base64 document size in bytes. |
| `LOCAL_MCP_DOCUMENT_PARSER_TIMEOUT_S` | `900` | `parse_document` | Timeout for Marker and MinerU CLI parsers. |
| `LOCAL_MCP_DOCUMENT_TMPDIR` | `.tmp/documents` | `parse_document` | Directory for downloaded/base64 documents and parser output temp files. |
| `LOCAL_MCP_MARKER_CMD` | auto-detected | `parse_document` | Optional path to the `marker_single` executable. |
| `LOCAL_MCP_MINERU_CMD` | auto-detected | `parse_document` | Optional path to the `mineru` executable. |
| `LOCAL_MCP_MINERU_BACKEND` | `pipeline` | `parse_document` | MinerU backend passed with `-b`; `pipeline` is CPU-friendly. |
| `LOCAL_MCP_FILE_OUTPUT_DIR` | required | `generate_file`, `web_search_to_file` | Destination folder for generated files. |
| `LOCAL_MCP_DOWNLOAD_DIR` | optional alias | `generate_file`, `web_search_to_file` | Used only when `LOCAL_MCP_FILE_OUTPUT_DIR` is empty. If neither is set, file-writing tools return an error. |

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

For OpenWebUI, run the server in HTTP mode and paste the contents of [`integrations/openwebui_tool.py`](../integrations/openwebui_tool.py) into OpenWebUI's tool editor. The bridge forwards OpenWebUI tool calls to `http://localhost:3002/mcp`.
