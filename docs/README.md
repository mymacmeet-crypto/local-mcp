# local-mcp Tool Documentation

This folder documents every tool exposed by the `local-mcp` MCP server.

`local-mcp` is a Python MCP server that helps AI clients search the web, discover URLs, extract readable Markdown from web pages, and run OCR on images. The tools are registered in [`server.py`](../server.py) with FastMCP and can also be used from OpenWebUI through [`openwebui_tool.py`](../openwebui_tool.py).

## Tool Index

| Tool | Documentation | Main purpose |
| --- | --- | --- |
| `web_search` | [web_search.md](web_search.md) | Search through a SearXNG instance and return citation-ready Markdown results. |
| `extract_urls` | [extract_urls.md](extract_urls.md) | Discover URLs from `robots.txt`, XML sitemaps, static HTML links, and optional browser-rendered pages. |
| `extract_content` | [extract_content.md](extract_content.md) | Fetch a page and return readable Markdown, with browser-render fallback for JavaScript-heavy pages. |
| `extract_image_text` | [extract_image_text.md](extract_image_text.md) | Extract text from local, remote, data URL, or base64 image input using Tesseract OCR. |

## Shared Project Setup

All tools use the same Python project setup:

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

Start the MCP server over stdio for desktop MCP clients:

```powershell
python server.py
```

Start the MCP server over Streamable HTTP for OpenWebUI or direct HTTP clients:

```powershell
python server.py --http
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
| `LOCAL_MCP_MIN_MARKDOWN_CHARS` | `200` | `extract_content` | Minimum static Markdown length before browser-render fallback is attempted. |
| `SEARXNG_BASE_URL` | `http://127.0.0.1:8888` | `web_search` | Default SearXNG base URL. |
| `SEARXNG_URLS` | unset | `web_search` | Comma-separated SearXNG failover list. |
| `LOCAL_MCP_SEARXNG_URLS` | unset | `web_search` | Alias for `SEARXNG_URLS`. |
| `SEARXNG_TIMEOUT_MS` | `LOCAL_MCP_TIMEOUT_MS` or `15000` | `web_search` | SearXNG request timeout in milliseconds. |
| `TESSERACT_CMD` | auto-detected | `extract_image_text` | Path to the native Tesseract executable. |
| `LOCAL_MCP_OCR_MAX_IMAGE_BYTES` | `20971520` | `extract_image_text` | Maximum accepted image size in bytes. |
| `LOCAL_MCP_TESSERACT_CONFIG` | empty | `extract_image_text` | Extra config string passed to Tesseract. |

## MCP Client Example

For Claude Desktop or another stdio MCP client, configure this repository's Python executable and `server.py`:

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

For OpenWebUI, run the server in HTTP mode and paste the contents of [`openwebui_tool.py`](../openwebui_tool.py) into OpenWebUI's tool editor. The bridge forwards OpenWebUI tool calls to `http://localhost:3002/mcp`.

