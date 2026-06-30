"""
OpenWebUI native tool for the claw-site MCP server in server.py.

Paste the entire contents of this file into OpenWebUI -> Tools -> Create Tool.
Make sure server.py is running in HTTP mode:

    python server.py --http

The server listens on http://localhost:3002/mcp by default.
"""

import json
from typing import Awaitable, Callable, Optional

import requests

MCP_SERVER_URL = "http://localhost:3002/mcp"
MCP_PROTOCOL_VERSION = "2024-11-05"

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
                    "clientInfo": {"name": "openwebui-claw-tool", "version": "1.1.0"},
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
            timeout=60,
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

    async def extract_content(
        self,
        url: str,
        include_title: bool = True,
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        Extract a page's readable content and return it as Markdown.
        Falls back to Crawl4AI browser rendering when static HTML yields little content.
        :param url: Page URL to extract. Scheme-less input like 'example.com' is allowed.
        :param include_title: Prepend the page title as a top-level Markdown heading.
        """
        _log("extract_content", f"url={url} include_title={include_title}")
        await self._emit_status(__event_emitter__, f"Extracting content from {url}...", False)

        result = self._call(
            "extract_content",
            {
                "url": url,
                "include_title": include_title,
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
