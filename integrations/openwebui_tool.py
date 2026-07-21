"""
OpenWebUI native tool for the local-mcp MCP server.

Paste the entire contents of this file into OpenWebUI -> Tools -> Create Tool.
Make sure local-mcp is running in HTTP mode:

    python -m local_mcp --http

The server listens on http://localhost:3002/mcp by default.

Live progress
-------------
Each tool call sends an MCP progress token to the server and reads the
`tools/call` SSE stream. The local-mcp tools emit `notifications/progress`
messages as they work (planning, searching, ranking, crawling, summarizing,
verifying, writing ...). This tool forwards each of those to OpenWebUI as a live
status update, so long-running tools like `deep_research` show real-time
progress in the chat instead of a single frozen spinner.

Result echoing
--------------
Synthesized answers (`smart_search`, `deep_research`, `generate_file`,
`extract_image_text`) are echoed into the chat as a message. Tools whose result
is raw source material for the model to analyze -- `web_search`, `web_fetch`,
`extract_urls`, `parse_document` -- report status only and are NOT dumped into
the chat (their full result still returns to the model as the tool output).
"""

import json
from typing import Awaitable, Callable, Optional

import httpx

MCP_SERVER_URL = "http://localhost:3002/mcp"
MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_REQUEST_TIMEOUT = 600

# Type alias for the OpenWebUI event emitter injected at call time.
EventEmitter = Optional[Callable[[dict], Awaitable[None]]]

# Sentinel: the server dropped our session (e.g. it restarted) -> reinitialize.
_SESSION_EXPIRED = object()


def _log(tag: str, msg: str) -> None:
    print(f"[MCP:{tag}] {msg}")


class Tools:
    def __init__(self):
        self._url = MCP_SERVER_URL
        self._session_id: Optional[str] = None
        self._req_id = 0
        self._progress_seq = 0
        _log("init", f"Tool initialized, server={self._url}")

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _next_progress_token(self) -> str:
        self._progress_seq += 1
        return f"owui-progress-{self._progress_seq}"

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        return headers

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=httpx.Timeout(MCP_REQUEST_TIMEOUT, connect=15.0))

    async def _init_session(self, client: httpx.AsyncClient) -> None:
        _log("init_session", "Sending initialize request...")
        async with client.stream(
            "POST",
            self._url,
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "openwebui-local-mcp-tool", "version": "2.0.0"},
                },
                "id": self._next_id(),
            },
            headers=self._headers(),
        ) as resp:
            _log(
                "init_session",
                f"initialize status={resp.status_code} content-type={resp.headers.get('content-type')}",
            )
            resp.raise_for_status()
            self._session_id = resp.headers.get("mcp-session-id")
            _log("init_session", f"session_id={self._session_id}")
            async for _ in resp.aiter_lines():
                pass

        _log("init_session", "Sending notifications/initialized...")
        notify = await client.post(
            self._url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers=self._headers(),
        )
        _log("init_session", f"notifications/initialized status={notify.status_code}")
        notify.raise_for_status()
        _log("init_session", "Session ready.")

    def _extract_result(self, data: dict) -> str:
        parts = data.get("result", {}).get("content", [])
        return "\n".join(part.get("text", "") for part in parts if part.get("type") == "text")

    @staticmethod
    def _progress_label(params: dict) -> str:
        progress = params.get("progress")
        total = params.get("total")
        if total:
            return f"Working... ({progress}/{total})"
        return "Working..."

    async def _handle_stream_message(self, data: dict, event_emitter: EventEmitter):
        """Handle one JSON-RPC message from the SSE stream.

        Returns the final result/error string once the response arrives, or
        ``None`` for notifications (progress/log) that keep the stream open.
        """
        method = data.get("method")
        if method == "notifications/progress":
            params = data.get("params", {})
            message = params.get("message") or self._progress_label(params)
            _log("progress", message)
            await self._emit_status(event_emitter, message, False)
            return None
        if method == "notifications/message":
            params = data.get("params", {})
            payload = params.get("data")
            if isinstance(payload, str) and payload.strip():
                await self._emit_status(event_emitter, payload.strip(), False)
            return None
        if method is not None:
            return None  # other server notifications: ignore, keep reading.
        if "result" in data:
            return self._extract_result(data)
        if "error" in data:
            return f"Error: {data['error'].get('message', 'unknown')}"
        return None

    async def _stream_tools_call(
        self,
        client: httpx.AsyncClient,
        tool_name: str,
        arguments: dict,
        event_emitter: EventEmitter,
    ):
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
                # Opting in to progress: the server only emits notifications/progress
                # when the request carries a progressToken.
                "_meta": {"progressToken": self._next_progress_token()},
            },
            "id": self._next_id(),
        }
        async with client.stream("POST", self._url, json=payload, headers=self._headers()) as resp:
            _log("call", f"response status={resp.status_code}")
            if resp.status_code == 404:
                return _SESSION_EXPIRED
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                async for raw in resp.aiter_lines():
                    if not raw or not raw.startswith("data: "):
                        continue
                    try:
                        data = json.loads(raw[6:])
                    except json.JSONDecodeError as err:
                        _log("parse", f"JSON decode error: {err}")
                        continue
                    outcome = await self._handle_stream_message(data, event_emitter)
                    if outcome is not None:
                        return outcome
                return "No response from server."

            body = await resp.aread()
            try:
                data = json.loads(body)
            except Exception as err:
                _log("parse", f"Failed to parse JSON: {err}")
                return f"Bad response: {body[:200]!r}"
            outcome = await self._handle_stream_message(data, event_emitter)
            return outcome if outcome is not None else "Unexpected response."

    async def _call(self, tool_name: str, arguments: dict, event_emitter: EventEmitter = None) -> str:
        arguments = {key: value for key, value in arguments.items() if value is not None}
        _log("call", f"tool={tool_name} args={arguments}")
        try:
            async with self._client() as client:
                if not self._session_id:
                    _log("call", "No session; initializing...")
                    await self._init_session(client)

                result = await self._stream_tools_call(client, tool_name, arguments, event_emitter)
                if result is _SESSION_EXPIRED:
                    _log("call", "Session not found (server restarted?); reinitializing...")
                    self._session_id = None
                    await self._init_session(client)
                    result = await self._stream_tools_call(client, tool_name, arguments, event_emitter)

                text = result if isinstance(result, str) else "Unexpected response."
                _log("call", f"final result: {text[:80]}")
                return text
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
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        STEP 1 of web research: DISCOVER candidate sources (discovery only, not an answer).
        Returns a JSON envelope with a list of candidate source `urls` and
        requires_fetch=true. The URLs alone are not evidence: do not answer from
        them. Next, call web_fetch on one or more of the urls, read the evidence,
        then write your own synthesized, cited answer.
        :param query: Search query to send to SearXNG.
        :param limit: Maximum number of URLs to return. Allowed range is 1 to 20.
        """
        _log("web_search", f"query={query} limit={limit}")
        await self._emit_status(__event_emitter__, f"Searching for {query}...", False)

        result = await self._call(
            "web_search",
            {"query": query, "limit": limit},
            __event_emitter__,
        )

        # Discovery data (raw URL list) is working material for the model, not a
        # user-facing answer: report status only, don't dump it into the chat.
        await self._emit_status(__event_emitter__, "Done", True)
        return result

    async def smart_search(
        self,
        query: str,
        max_sources: int = 3,
        time_range: str = "",
        model: str = "",
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        One-shot web answer powered by an LLM. Searches the web, lets the LLM
        rank the most relevant sources, crawls them, and returns an LLM-written
        summary that already cites its sources. Unlike web_search (discovery only),
        this returns a FINAL, synthesized answer plus the list of source URLs used.
        Uses a local Ollama model by default (LLM_PROVIDER=ollama on the server);
        set LLM_PROVIDER=gemini and GEMINI_API_KEY on the server to use Gemini instead.
        :param query: The question or topic to research and answer.
        :param max_sources: Maximum number of pages to crawl and summarize. Allowed range is 1 to 10.
        :param time_range: Optional SearXNG time range: 'day', 'month', or 'year'. Empty means any time.
        :param model: Optional model override for the configured LLM provider. Empty uses the provider default.
        """
        _log("smart_search", f"query={query} max_sources={max_sources} time_range={time_range} model={model}")
        await self._emit_status(__event_emitter__, f"Researching {query}...", False)

        result = await self._call(
            "smart_search",
            {"query": query, "max_sources": max_sources, "time_range": time_range, "model": model},
            __event_emitter__,
        )

        await self._emit_status(__event_emitter__, "Done", True)
        # The result IS the synthesized, cited answer -> echo it to the user.
        await self._emit_message(__event_emitter__, f"\n{result}\n")
        return result

    async def deep_research(
        self,
        query: str,
        breadth: int = 4,
        max_iterations: int = 2,
        max_sources: int = 12,
        time_range: str = "",
        verify: bool = True,
        output_file: str = "",
        model: str = "",
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        Multi-source, verified research report: an iterative, deeper version of
        smart_search. Plans sub-questions, runs several rounds of web search +
        crawl, takes per-source notes, reflects on gaps to open follow-up
        searches, then synthesizes a long-form, cited Markdown report and runs a
        claim-verification pass. Prefer smart_search for a quick one-shot answer;
        use deep_research when the question is broad or high-stakes. Streams live
        progress for each stage. Uses a local Ollama model by default
        (LLM_PROVIDER=ollama on the server); set LLM_PROVIDER=gemini and
        GEMINI_API_KEY on the server to use Gemini instead.
        :param query: The research question or topic to investigate in depth.
        :param breadth: New sources to crawl per research round. Allowed range is 1 to 10.
        :param max_iterations: How many reflect -> re-search rounds to run (research depth). Allowed range is 1 to 4.
        :param max_sources: Hard cap on total pages crawled across all rounds. Allowed range is 1 to 30.
        :param time_range: Optional SearXNG time range: 'day', 'month', or 'year'. Empty means any time.
        :param verify: Run a fact-checking pass that flags report claims the sources do not support.
        :param output_file: Optional relative Markdown/PDF filename. When set, the report is also written to a file.
        :param model: Optional model override for the configured LLM provider. Empty uses the provider default.
        """
        _log(
            "deep_research",
            f"query={query} breadth={breadth} max_iterations={max_iterations} "
            f"max_sources={max_sources} time_range={time_range} verify={verify} output_file={output_file}",
        )
        await self._emit_status(__event_emitter__, f"Starting deep research on {query}...", False)

        result = await self._call(
            "deep_research",
            {
                "query": query,
                "breadth": breadth,
                "max_iterations": max_iterations,
                "max_sources": max_sources,
                "time_range": time_range,
                "verify": verify,
                "output_file": output_file,
                "model": model,
            },
            __event_emitter__,
        )

        await self._emit_status(__event_emitter__, "Done", True)
        # The result IS the final cited report -> echo it to the user.
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

        result = await self._call(
            "extract_urls",
            {"url": url, "same_domain": same_domain, "same_path": same_path, "limit": limit},
            __event_emitter__,
        )

        # A raw URL list is working material -> status only, no chat dump.
        await self._emit_status(__event_emitter__, "Done", True)
        return result

    async def web_fetch(
        self,
        url: str,
        max_chars: int = 120000,
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        STEP 2 of web research: RETRIEVE one page's full content as evidence.
        Returns a JSON envelope with the page url and its Markdown content. The content is raw
        source material (internal working material): do NOT paste content, markdown, HTML, or
        long text blocks to the user. Read it, extract the relevant facts, and write your own
        concise, cited answer.
        :param url: Page URL to fetch. Scheme-less input like 'example.com' is allowed.
        :param max_chars: Maximum content characters to return before truncation. Use 0 for no truncation.
        """
        _log("web_fetch", f"url={url} max_chars={max_chars}")
        await self._emit_status(__event_emitter__, f"Fetching {url}...", False)

        result = await self._call(
            "web_fetch",
            {"url": url, "max_chars": max_chars},
            __event_emitter__,
        )

        # Fetched page content is evidence for the model, not a user-facing
        # answer (the tool's own guidance says do NOT paste it) -> status only.
        await self._emit_status(__event_emitter__, "Done", True)
        return result

    async def schedule_task(
        self,
        name: str,
        command: str,
        schedule: str,
        scheduler: str = "auto",
        description: str = "",
        working_directory: str = "",
        environment: str = "",
        overwrite: bool = True,
        install: bool = True,
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        Create and install a cron, launchd, or n8n scheduled task for a recurring local command.
        The schedule is installed automatically; the result says whether it is live.
        :param name: Human-readable task name.
        :param command: Shell command or script body to run on the schedule.
        :param schedule: Five-field cron expression, or alias: hourly, daily, weekdays, weekly, monthly.
        :param scheduler: Scheduler to use: auto, cron, launchd, systemd, or n8n. auto picks the best available on this host.
        :param description: Optional task description written into the generated README.
        :param working_directory: Optional working directory for the generated runner script.
        :param environment: Optional environment variables as KEY=VALUE lines or comma-separated assignments.
        :param overwrite: Replace existing generated files for this task.
        :param install: Install the schedule after generating files. Default true; n8n is always manual import.
        """
        _log("schedule_task", f"name={name} schedule={schedule} scheduler={scheduler} install={install}")
        await self._emit_status(__event_emitter__, f"Generating scheduled task {name}...", False)

        result = await self._call(
            "schedule_task",
            {
                "name": name,
                "command": command,
                "schedule": schedule,
                "scheduler": scheduler,
                "description": description,
                "working_directory": working_directory,
                "environment": environment,
                "overwrite": overwrite,
                "install": install,
            },
            __event_emitter__,
        )

        await self._emit_status(__event_emitter__, "Done", True)
        await self._emit_message(__event_emitter__, f"\n{result}\n")
        return result

    async def list_scheduled_tasks(
        self,
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        List scheduled tasks created by schedule_task and whether each is installed.
        """
        _log("list_scheduled_tasks", "listing")
        await self._emit_status(__event_emitter__, "Listing scheduled tasks...", False)

        result = await self._call("list_scheduled_tasks", {}, __event_emitter__)

        await self._emit_status(__event_emitter__, "Done", True)
        await self._emit_message(__event_emitter__, f"\n{result}\n")
        return result

    async def delete_scheduled_task(
        self,
        name: str,
        delete_files: bool = True,
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        Uninstall a scheduled task created by schedule_task and optionally delete its files.
        :param name: Task name or slug used when the task was created.
        :param delete_files: Also delete the generated bundle files, not just the installed schedule.
        """
        _log("delete_scheduled_task", f"name={name} delete_files={delete_files}")
        await self._emit_status(__event_emitter__, f"Removing scheduled task {name}...", False)

        result = await self._call("delete_scheduled_task", {"name": name, "delete_files": delete_files}, __event_emitter__)

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

        result = await self._call(
            "extract_image_text",
            {"image": image, "lang": lang},
            __event_emitter__,
        )

        await self._emit_status(__event_emitter__, "Done", True)
        # The extracted text is the deliverable -> echo it as a code block.
        await self._emit_message(__event_emitter__, f"\n**Extracted text:**\n```\n{result}\n```\n")
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

        result = await self._call(
            "parse_document",
            {
                "document": document,
                "parser": parser,
                "output_format": output_format,
                "pages": pages,
                "include_metadata": include_metadata,
                "max_chars": max_chars,
            },
            __event_emitter__,
        )

        # Parsed document content is source material for the model -> status only.
        await self._emit_status(__event_emitter__, "Done", True)
        return result

    async def generate_file(
        self,
        filename: str,
        content: str = "",
        query: str = "",
        search_mode: str = "smart",
        file_type: str = "md",
        overwrite: bool = False,
        write_mode: str = "write",
        max_sources: int = 0,
        time_range: str = "",
        model: str = "",
        min_words: int = 0,
        ensure_trailing_newline: bool = True,
        __event_emitter__: EventEmitter = None,
    ) -> str:
        """
        Generate a local md/txt/pdf/docx/pptx file from supplied content or from web research.
        Provide exactly one of content or query. With content, the supplied text is written
        as-is. With query, the server researches the question online first (search_mode
        'smart' for a fast cited summary, 'deep' for an iterative research report) and
        writes the result to the file.
        :param filename: Output filename or relative path. The extension matching file_type is appended when omitted.
        :param content: Ready-made Markdown-like content to write. Leave empty when using query.
        :param query: Research question to answer and write to the file. Leave empty when using content.
        :param search_mode: Research pipeline for query mode: 'smart' (fast summary) or 'deep' (thorough report).
        :param file_type: Output file type: md/markdown, txt, pdf, doc/docx (Word), or ppt/pptx (PowerPoint).
        :param overwrite: Replace an existing file at the target path.
        :param write_mode: 'write' creates/replaces the file; 'append' adds a chunk (Markdown and text files only).
        :param max_sources: Maximum web sources for query mode. 0 uses the search mode's default.
        :param time_range: Optional SearXNG time range for query mode: 'day', 'month', or 'year'.
        :param model: Optional model override for the configured LLM provider in query mode.
        :param min_words: Minimum word count required for supplied content. 0 allows short notes.
        :param ensure_trailing_newline: Append a trailing newline to Markdown/text output. Ignored for binary output.
        """
        _log(
            "generate_file",
            f"filename={filename} file_type={file_type} mode={write_mode} query={query!r} search_mode={search_mode}",
        )
        status = f"Researching and writing {query}..." if query.strip() else "Generating file..."
        await self._emit_status(__event_emitter__, status, False)

        result = await self._call(
            "generate_file",
            {
                "filename": filename,
                "content": content,
                "query": query,
                "search_mode": search_mode,
                "file_type": file_type,
                "overwrite": overwrite,
                "write_mode": write_mode,
                "max_sources": max_sources,
                "time_range": time_range,
                "model": model,
                "min_words": min_words,
                "ensure_trailing_newline": ensure_trailing_newline,
            },
            __event_emitter__,
        )

        await self._emit_status(__event_emitter__, "Done", True)
        # The result is a short "file generated" summary -> echo it to the user.
        await self._emit_message(__event_emitter__, f"\n{result}\n")
        return result
