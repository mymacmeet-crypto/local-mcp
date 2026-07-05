"""
OpenWebUI native tool for the local-mcp MCP server.

Paste the entire contents of this file into OpenWebUI -> Tools -> Create Tool.
Make sure local-mcp is running in HTTP mode:

    python -m local_mcp --http

The server listens on http://localhost:3002/mcp by default.
"""

import json
from typing import Awaitable, Callable, Optional

import requests

MCP_SERVER_URL = "http://localhost:3002/mcp"
MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_REQUEST_TIMEOUT = 600

# Type alias for the OpenWebUI event emitter injected at call time.
EventEmitter = Optional[Callable[[dict], Awaitable[None]]]


def _log(tag: str, msg: str) -> None:
    print(f"[MCP:{tag}] {msg}")


class Tools:
    def __init__(self):
        self._url = MCP_SERVER_URL
        self._session_id: Optional[str] = None
        self._req_id = 0
        _log("init", f"Tool initialized, server={self._url}")

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        return headers

    def _init_session(self) -> None:
        _log("init_session", "Sending initialize request...")
        resp = requests.post(
            self._url,
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "openwebui-local-mcp-tool", "version": "1.1.0"},
                },
                "id": self._next_id(),
            },
            headers=self._headers(),
            timeout=15,
            stream=True,
        )
        _log(
            "init_session",
            f"initialize status={resp.status_code} content-type={resp.headers.get('Content-Type')}",
        )
        resp.raise_for_status()
        self._session_id = resp.headers.get("mcp-session-id")
        _log("init_session", f"session_id={self._session_id}")

        for _ in resp.iter_lines():
            pass

        _log("init_session", "Sending notifications/initialized...")
        notify = requests.post(
            self._url,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            headers=self._headers(),
            timeout=15,
            stream=True,
        )
        _log("init_session", f"notifications/initialized status={notify.status_code}")
        notify.raise_for_status()
        for _ in notify.iter_lines():
            pass
        _log("init_session", "Session ready.")

    def _parse(self, resp: requests.Response) -> str:
        content_type = resp.headers.get("Content-Type", "")
        _log("parse", f"content-type={content_type}")

        if "text/event-stream" in content_type:
            _log("parse", "Reading SSE stream line by line...")
            for raw in resp.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                _log("parse", f"SSE line: {line[:120]}")
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                    except json.JSONDecodeError as err:
                        _log("parse", f"JSON decode error: {err}")
                        continue

                    if "result" in data:
                        parts = data["result"].get("content", [])
                        text = "\n".join(
                            part["text"]
                            for part in parts
                            if part.get("type") == "text"
                        )
                        _log("parse", f"result text: {text[:80]}")
                        return text
                    if "error" in data:
                        msg = data["error"].get("message", "unknown")
                        _log("parse", f"error from server: {msg}")
                        return f"Error: {msg}"
            return "No response from server."

        body = resp.text
        _log("parse", f"JSON body: {body[:200]}")
        try:
            data = resp.json()
        except Exception as err:
            _log("parse", f"Failed to parse JSON: {err}")
            return f"Bad response: {body[:200]}"

        if "result" in data:
            parts = data["result"].get("content", [])
            return "\n".join(part["text"] for part in parts if part.get("type") == "text")
        if "error" in data:
            return f"Error: {data['error'].get('message', 'unknown')}"
        return "Unexpected response."

    def _do_call(self, tool_name: str, arguments: dict) -> requests.Response:
        resp = requests.post(
            self._url,
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
                "id": self._next_id(),
            },
            headers=self._headers(),
            timeout=MCP_REQUEST_TIMEOUT,
            stream=True,
        )
        _log("call", f"response status={resp.status_code}")
        return resp

    def _call(self, tool_name: str, arguments: dict) -> str:
        arguments = {key: value for key, value in arguments.items() if value is not None}
        _log("call", f"tool={tool_name} args={arguments}")
        try:
            if not self._session_id:
                _log("call", "No session; initializing...")
                self._init_session()

            _log("call", f"POSTing tools/call for {tool_name}...")
            resp = self._do_call(tool_name, arguments)

            if resp.status_code == 404:
                _log("call", "Session not found (server restarted?); reinitializing...")
                self._session_id = None
                self._init_session()
                resp = self._do_call(tool_name, arguments)

            resp.raise_for_status()
            result = self._parse(resp)
            _log("call", f"final result: {result[:80]}")
            return result
        except Exception as err:
            _log("call", f"EXCEPTION: {err}")
            self._session_id = None
            return f"Error calling {tool_name}: {err}"

    async def _emit_status(
        self,
        event_emitter: EventEmitter,
        description: str,
        done: bool,
    ) -> None:
        if event_emitter:
            await event_emitter(
                {"type": "status", "data": {"description": description, "done": done}}
            )

    async def _emit_message(self, event_emitter: EventEmitter, content: str) -> None:
        if event_emitter:
            await event_emitter({"type": "message", "data": {"content": content}})

    # ------------------------------------------------------------------ #
    # Tools                                                                #
    # ------------------------------------------------------------------ #

    async def web_search(
        self,
        query: str,
        limit: int = 8,
        categories: str = "general",
        language: str = "auto",
        pageno: int = 1,
        safesearch: int = 0,
        time_range: str = "",
        engines: str = "",
        searxng_url: str = "",
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        Search the web through SearXNG and return citation-ready Markdown results.
        :param query: Search query to send to SearXNG.
        :param limit: Maximum number of search results to return. Allowed range is 1 to 20.
        :param categories: SearXNG categories, for example 'general', 'news', 'images', or 'general,news'.
        :param language: SearXNG language code. Use 'auto' for automatic language detection.
        :param pageno: SearXNG result page number. Allowed range is 1 to 20.
        :param safesearch: Safe-search level, where 0 is off, 1 is moderate, and 2 is strict.
        :param time_range: Optional SearXNG time range: 'day', 'month', or 'year'.
        :param engines: Optional comma-separated SearXNG engines override.
        :param searxng_url: Optional SearXNG base URL for this request.
        """
        _log(
            "web_search",
            f"query={query} limit={limit} categories={categories} language={language}",
        )
        await self._emit_status(__event_emitter__, f"Searching for {query}...", False)

        result = self._call(
            "web_search",
            {
                "query": query,
                "limit": limit,
                "categories": categories,
                "language": language,
                "pageno": pageno,
                "safesearch": safesearch,
                "time_range": time_range,
                "engines": engines,
                "searxng_url": searxng_url,
            },
        )

        await self._emit_status(__event_emitter__, "Done", True)
        await self._emit_message(__event_emitter__, f"\n{result}\n")
        return result

    async def web_summarize(
        self,
        query: str = "",
        urls: str = "",
        limit: int = 5,
        categories: str = "general",
        language: str = "auto",
        pageno: int = 1,
        safesearch: int = 0,
        time_range: str = "",
        engines: str = "",
        searxng_url: str = "",
        render: str = "auto",
        selector: str = "",
        summary_sentences: int = 3,
        max_chars_per_page: int = 30000,
        include_failures: bool = True,
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        Search or fetch multiple URLs and return concise summaries instead of full page content.
        :param query: Optional search query. When provided, SearXNG result URLs are fetched and summarized.
        :param urls: Optional URLs, web_search Markdown, or Markdown links to summarize directly.
        :param limit: Maximum number of URLs to fetch and summarize. Allowed range is 1 to 20.
        :param categories: SearXNG categories when query is provided.
        :param language: SearXNG language code when query is provided.
        :param pageno: SearXNG result page number when query is provided.
        :param safesearch: SearXNG safe-search level when query is provided.
        :param time_range: Optional SearXNG time range when query is provided.
        :param engines: Optional comma-separated SearXNG engines override when query is provided.
        :param searxng_url: Optional SearXNG base URL when query is provided.
        :param render: Fetch mode for each URL: auto, static, or browser.
        :param selector: Optional CSS selector to summarize a specific page region.
        :param summary_sentences: Maximum sentences per page summary.
        :param max_chars_per_page: Maximum extracted page characters to consider before summarizing.
        :param include_failures: Include URLs that failed to fetch in the response.
        """
        _log("web_summarize", f"query={query} urls_len={len(urls or '')} limit={limit} render={render}")
        await self._emit_status(__event_emitter__, "Summarizing web sources...", False)

        result = self._call(
            "web_summarize",
            {
                "query": query,
                "urls": urls,
                "limit": limit,
                "categories": categories,
                "language": language,
                "pageno": pageno,
                "safesearch": safesearch,
                "time_range": time_range,
                "engines": engines,
                "searxng_url": searxng_url,
                "render": render,
                "selector": selector,
                "summary_sentences": summary_sentences,
                "max_chars_per_page": max_chars_per_page,
                "include_failures": include_failures,
            },
        )

        await self._emit_status(__event_emitter__, "Done", True)
        await self._emit_message(__event_emitter__, f"\n{result}\n")
        return result

    async def web_search_to_file(
        self,
        query: str,
        filename: str,
        limit: int = 8,
        categories: str = "general",
        language: str = "auto",
        pageno: int = 1,
        safesearch: int = 0,
        time_range: str = "",
        engines: str = "",
        searxng_url: str = "",
        write_mode: str = "append",
        overwrite: bool = False,
        ensure_trailing_newline: bool = True,
        file_type: str = "md",
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        Search the web through SearXNG and write citation-ready results to a local Markdown or PDF file.
        :param query: Search query to send to SearXNG.
        :param filename: Output Markdown or PDF filename or relative path. The matching extension is appended when omitted.
        :param limit: Maximum number of search results to write. Allowed range is 1 to 20.
        :param categories: SearXNG categories, for example 'general', 'news', 'images', or 'general,news'.
        :param language: SearXNG language code. Use 'auto' for automatic language detection.
        :param pageno: SearXNG result page number. Allowed range is 1 to 20.
        :param safesearch: Safe-search level, where 0 is off, 1 is moderate, and 2 is strict.
        :param time_range: Optional SearXNG time range: 'day', 'month', or 'year'.
        :param engines: Optional comma-separated SearXNG engines override.
        :param searxng_url: Optional SearXNG base URL for this request.
        :param write_mode: File write mode. Use 'append' to add a search section or 'write' to create/replace.
        :param overwrite: Replace an existing file when write_mode is 'write'.
        :param ensure_trailing_newline: Append a trailing newline to the generated Markdown section. Ignored for PDF output.
        :param file_type: Output file type: md/markdown or pdf. A .pdf filename also selects PDF output.
        """
        _log("web_search_to_file", f"query={query} filename={filename} file_type={file_type} mode={write_mode}")
        await self._emit_status(__event_emitter__, f"Searching and writing {query}...", False)

        result = self._call(
            "web_search_to_file",
            {
                "query": query,
                "filename": filename,
                "limit": limit,
                "categories": categories,
                "language": language,
                "pageno": pageno,
                "safesearch": safesearch,
                "time_range": time_range,
                "engines": engines,
                "searxng_url": searxng_url,
                "write_mode": write_mode,
                "overwrite": overwrite,
                "ensure_trailing_newline": ensure_trailing_newline,
                "file_type": file_type,
            },
        )

        await self._emit_status(__event_emitter__, "Done", True)
        await self._emit_message(__event_emitter__, f"\n{result}\n")
        return result

    async def extract_urls(
        self,
        url: str,
        same_domain: bool = True,
        same_path: bool = True,
        limit: int = 500,
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        Extract unique absolute URLs from robots.txt, sitemaps, and page links.
        Falls back to Crawl4AI browser rendering when static HTML has no links.
        :param url: Page or site URL. Scheme-less input like 'example.com' is allowed.
        :param same_domain: Only return URLs on the input URL hostname.
        :param same_path: Only return URLs under the input URL path prefix, such as /blogs and /blogs/...
        :param limit: Maximum number of unique URLs to return. Allowed range is 1 to 5000.
        """
        _log(
            "extract_urls",
            f"url={url} same_domain={same_domain} same_path={same_path} limit={limit}",
        )
        await self._emit_status(__event_emitter__, f"Crawling {url}...", False)

        result = self._call(
            "extract_urls",
            {
                "url": url,
                "same_domain": same_domain,
                "same_path": same_path,
                "limit": limit,
            },
        )

        await self._emit_status(__event_emitter__, "Done", True)
        await self._emit_message(__event_emitter__, f"\n{result}\n")
        return result

    async def web_fetch(
        self,
        url: str,
        render: str = "auto",
        output_format: str = "markdown",
        selector: str = "",
        include_links: bool = False,
        include_images: bool = False,
        include_metadata: bool = True,
        max_chars: int = 120000,
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        Fetch, browser-render, or scrape a web page into Markdown, text, HTML, or JSON.
        :param url: Page URL to fetch. Scheme-less input like 'example.com' is allowed.
        :param render: Fetch mode: auto, static, or browser.
        :param output_format: Returned content format: markdown, text, html, or json.
        :param selector: Optional CSS selector for scraping a specific page region.
        :param include_links: Include scraped links from the page or selected region.
        :param include_images: Include scraped image URLs from the page or selected region.
        :param include_metadata: Include fetch metadata before non-JSON content.
        :param max_chars: Maximum content characters to return before truncation. Use 0 for no truncation.
        """
        _log(
            "web_fetch",
            f"url={url} render={render} output_format={output_format} selector={selector}",
        )
        await self._emit_status(__event_emitter__, f"Fetching {url}...", False)

        result = self._call(
            "web_fetch",
            {
                "url": url,
                "render": render,
                "output_format": output_format,
                "selector": selector,
                "include_links": include_links,
                "include_images": include_images,
                "include_metadata": include_metadata,
                "max_chars": max_chars,
            },
        )

        await self._emit_status(__event_emitter__, "Done", True)
        await self._emit_message(__event_emitter__, f"\n{result}\n")
        return result

    async def extract_image_text(
        self,
        image: str,
        lang: str = "eng",
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        Extract text from an image using Tesseract OCR.
        :param image: Image file path, image URL, data URL, or base64-encoded image content.
        :param lang: Tesseract language code, for example 'eng' or 'eng+hin'. Default is 'eng'.
        """
        _log("extract_image_text", f"image={image[:60]} lang={lang}")
        await self._emit_status(__event_emitter__, "Running OCR...", False)

        result = self._call("extract_image_text", {"image": image, "lang": lang})

        await self._emit_status(__event_emitter__, "Done", True)
        await self._emit_message(
            __event_emitter__,
            f"\n**Extracted text:**\n```\n{result}\n```\n",
        )
        return result

    async def parse_document(
        self,
        document: str,
        parser: str = "auto",
        output_format: str = "markdown",
        pages: str = "",
        include_metadata: bool = True,
        max_chars: int = 120000,
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        Parse a PDF or document into Markdown, text, or JSON.
        :param document: Document file path, file URL, HTTP(S) URL, data URL, or base64 document content.
        :param parser: Parser backend: auto, pypdf, pymupdf4llm, pdfplumber, docling, marker, mineru, or text.
        :param output_format: Output format: markdown, text, or json.
        :param pages: Optional 1-based page range like '1-3,5'. Empty parses all pages.
        :param include_metadata: Include parser/source metadata before Markdown or text output.
        :param max_chars: Maximum returned content characters before truncation.
        """
        _log(
            "parse_document",
            f"document={document[:80]} parser={parser} output_format={output_format} pages={pages}",
        )
        await self._emit_status(__event_emitter__, "Parsing document...", False)

        result = self._call(
            "parse_document",
            {
                "document": document,
                "parser": parser,
                "output_format": output_format,
                "pages": pages,
                "include_metadata": include_metadata,
                "max_chars": max_chars,
            },
        )

        await self._emit_status(__event_emitter__, "Done", True)
        await self._emit_message(__event_emitter__, f"\n{result}\n")
        return result

    async def generate_file(
        self,
        filename: str,
        content: str,
        file_type: str = "md",
        output_dir: str = "",
        write_mode: str = "write",
        overwrite: bool = False,
        ensure_trailing_newline: bool = True,
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        Generate a local Markdown or PDF file from supplied content.
        :param filename: Output Markdown or PDF filename or relative path. The extension is appended when omitted.
        :param content: Markdown-like content to write into the generated Markdown or PDF file.
        :param file_type: Output file type: md/markdown or pdf. A .pdf filename also selects PDF output.
        :param output_dir: Reserved for compatibility. The server uses LOCAL_MCP_FILE_OUTPUT_DIR or LOCAL_MCP_DOWNLOAD_DIR.
        :param write_mode: Write mode. Use 'write' for normal generation or 'append' to add this content as a chunk.
        :param overwrite: Replace an existing file at the target path.
        :param ensure_trailing_newline: Append a trailing newline to non-empty Markdown content. Ignored for PDF output.
        """
        _log("generate_file", f"filename={filename} file_type={file_type} mode={write_mode} output_dir={output_dir}")
        await self._emit_status(__event_emitter__, "Generating file...", False)

        result = self._call(
            "generate_file",
            {
                "filename": filename,
                "content": content,
                "file_type": file_type,
                "overwrite": overwrite,
                "write_mode": write_mode,
                "ensure_trailing_newline": ensure_trailing_newline,
            },
        )

        await self._emit_status(__event_emitter__, "Done", True)
        await self._emit_message(__event_emitter__, f"\n{result}\n")
        return result
