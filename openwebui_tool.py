"""
OpenWebUI native tool for claw-site MCP server (server.py).
Paste the entire contents of this file into OpenWebUI → Tools → Create Tool.
Make sure server.py is running in HTTP mode:  python server.py --http  (port 3002)
"""

import json
import requests
from typing import Optional, Callable, Awaitable, Any

MCP_SERVER_URL = "http://localhost:3002/mcp"
MCP_PROTOCOL_VERSION = "2024-11-05"

# Type alias for the OpenWebUI event emitter injected at call time
EventEmitter = Optional[Callable[[dict], Awaitable[None]]]


def _log(tag: str, msg: str) -> None:
    print(f"[MCP:{tag}] {msg}")


class Tools:
    def __init__(self):
        self._url = MCP_SERVER_URL
        self._session_id: Optional[str] = None
        self._req_id = 0
        _log("init", f"Tool initialised, server={self._url}")

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _headers(self) -> dict:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            h["mcp-session-id"] = self._session_id
        return h

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
                    "clientInfo": {"name": "openwebui-claw-tool", "version": "1.0.0"},
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
        for _ in notify.iter_lines():
            pass
        _log("init_session", "Session ready.")

    def _parse(self, resp: requests.Response) -> str:
        ct = resp.headers.get("Content-Type", "")
        _log("parse", f"content-type={ct}")

        if "text/event-stream" in ct:
            _log("parse", "Reading SSE stream line by line...")
            for raw in resp.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                _log("parse", f"SSE line: {line[:120]}")
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if "result" in data:
                            parts = data["result"].get("content", [])
                            text = "\n".join(
                                p["text"] for p in parts if p.get("type") == "text"
                            )
                            _log("parse", f"result text: {text[:80]}")
                            return text
                        if "error" in data:
                            msg = data["error"].get("message", "unknown")
                            _log("parse", f"error from server: {msg}")
                            return f"Error: {msg}"
                    except json.JSONDecodeError as e:
                        _log("parse", f"JSON decode error: {e}")
            return "No response from server."

        body = resp.text
        _log("parse", f"JSON body: {body[:200]}")
        try:
            data = resp.json()
        except Exception as e:
            _log("parse", f"Failed to parse JSON: {e}")
            return f"Bad response: {body[:200]}"

        if "result" in data:
            parts = data["result"].get("content", [])
            return "\n".join(p["text"] for p in parts if p.get("type") == "text")
        if "error" in data:
            return f"Error: {data['error'].get('message', 'unknown')}"
        return "Unexpected response."

    def _call(self, tool_name: str, arguments: dict) -> str:
        arguments = {k: v for k, v in arguments.items() if v is not None}
        _log("call", f"tool={tool_name} args={arguments}")
        try:
            if not self._session_id:
                _log("call", "No session — initialising...")
                self._init_session()

            _log("call", f"POSTing tools/call for {tool_name}...")
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
            resp.raise_for_status()
            result = self._parse(resp)
            _log("call", f"final result: {result[:80]}")
            return result
        except Exception as e:
            _log("call", f"EXCEPTION: {e}")
            self._session_id = None
            return f"Error calling {tool_name}: {e}"

    # ------------------------------------------------------------------ #
    # Tools                                                                #
    # ------------------------------------------------------------------ #

    async def extract_urls(
        self,
        url: str,
        same_domain: bool = True,
        same_path: bool = True,
        limit: int = 500,
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        Extract unique absolute URLs from a website via robots.txt, sitemaps, and page scraping.
        Falls back to browser rendering (Crawl4AI) when static HTML has no links.
        :param url: Page or site URL to crawl. Scheme-less input like 'example.com' is allowed.
        :param same_domain: Only return URLs on the same hostname as the input URL.
        :param same_path: Only return URLs under the input URL path prefix (e.g. /blog and /blog/...).
        :param limit: Maximum number of unique URLs to return (1–5000, default 500).
        """
        _log("extract_urls", f"url={url} same_domain={same_domain} same_path={same_path} limit={limit}")

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Crawling {url}…", "done": False}})

        result = self._call(
            "extract_urls",
            {
                "url": url,
                "same_domain": same_domain,
                "same_path": same_path,
                "limit": limit,
            },
        )

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Done", "done": True}})
            await __event_emitter__({"type": "message", "data": {"content": f"\n{result}\n"}})

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
        :param lang: Tesseract language code, e.g. 'eng' or 'eng+hin'. Default is 'eng'.
        """
        _log("extract_image_text", f"image={image[:60]} lang={lang}")

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Running OCR…", "done": False}})

        result = self._call("extract_image_text", {"image": image, "lang": lang})

        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Done", "done": True}})
            await __event_emitter__({"type": "message", "data": {"content": f"\n**Extracted text:**\n```\n{result}\n```\n"}})

        return result
