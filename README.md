# local-mcp

`local-mcp` is a small Python MCP server with tools for SearXNG web search, fetching/browsing/scraping web pages, summarizing multiple web pages, extracting site URLs, extracting text from images, parsing PDFs/documents, and generating local Markdown or PDF files.

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
pip install ".[agents-langgraph]"     # LangGraph engine for tool-using agent teams
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

The `simple` profile registers simpler wrapper tools plus the unified file tool:

- `fetch_web_page`
- `list_page_urls`
- `read_document`
- `read_image_text`
- `generate_file`

For reports, set `min_words` on `generate_file` (for example `min_words=900`). It rejects content below the threshold, so smaller models are forced to expand the report before a half-page file is written.

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

## Tools

### `web_search`

Parameters:

- `query`: search query to send to SearXNG.
- `limit`: maximum number of URLs to return. Default: `8`. Allowed range: `1` to `20`.

`web_search` is a **discovery** tool, not an answer tool. It returns a minimal JSON envelope: `stage`, `query`, `requires_fetch`, `workflow`, `agent_guidance`, `next_action`, and a `urls` list of candidate source URLs (in SearXNG order). The URLs alone are not evidence: the intended next step is to call `web_fetch` on one or more of the `urls`, then synthesize an answer from the fetched content.

### `smart_search`

Parameters:

- `query`: the question or topic to research and answer.
- `max_sources`: maximum number of pages to crawl and summarize. Default: `3`. Allowed range: `1` to `10`.
- `time_range`: optional SearXNG time range: `day`, `month`, or `year`. Empty means any time.
- `model`: optional model override for the configured LLM provider. Empty uses `OLLAMA_MODEL` or `GEMINI_MODEL`, whichever `LLM_PROVIDER` selects.

`smart_search` is a one-shot **answer** tool that runs the whole research pipeline internally: it searches SearXNG for candidate sources, asks an LLM to rank them by relevance, crawls the ranked pages (falling through to lower-ranked sources when a page times out or blocks the request) until `max_sources` load successfully, then asks the LLM to write a synthesized, inline-cited summary. It returns plain text — the summary followed by a numbered `Sources:` list of the URLs actually used — unlike `web_search`, which returns intermediate JSON for the model to process itself.

Uses a local Ollama model by default (`LLM_PROVIDER=ollama`, `OLLAMA_MODEL=qwen2.5:7b`) — no API key needed, just a running `ollama serve` with the model pulled. Set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY` in `.env` (see `.env.example`) to use Google Gemini instead. No extra Python dependency is needed for either backend — the client calls the REST API directly over `httpx`.

### `deep_research`

Parameters:

- `query`: the research question or topic to investigate in depth.
- `breadth`: new sources to crawl per research round. Default: `4`. Allowed range: `1` to `10`.
- `max_iterations`: how many reflect → re-search rounds to run (research depth). Default: `2`. Allowed range: `1` to `4`.
- `max_sources`: hard cap on total pages crawled across all rounds. Default: `12`. Allowed range: `1` to `30`.
- `time_range`: optional SearXNG time range: `day`, `month`, or `year`. Empty means any time.
- `verify`: run a fact-checking pass that flags report claims the sources do not support. Default: `true`.
- `output_file`: optional relative Markdown/PDF filename. When set, the report is also written to a file and its path is returned.
- `model`: optional model override for the configured LLM provider.

`deep_research` is an iterative, deeper version of `smart_search`. It **plans** sub-questions and an outline, runs several rounds of search + crawl, takes compact per-source notes (an evidence ledger, rather than concatenating whole pages), **reflects** on what is still missing to open follow-up searches, then **synthesizes** a long-form, sectioned Markdown report with inline `[n]` citations and a claim-**verification** pass. It returns the report followed by a numbered `Sources` list, and can write it to a file. Prefer `smart_search` for a quick one-shot answer; prefer `deep_research` for broad or high-stakes questions worth reading many sources and cross-checking. It uses the same pluggable LLM backend as `smart_search`. See [`docs/deep_research.md`](docs/deep_research.md).

### `web_fetch`

Parameters:

- `url`: page URL to fetch. Scheme-less input like `example.com` is allowed.
- `max_chars`: maximum `content` characters before truncation. Use `0` for no truncation. Default: `120000`.

`web_fetch` is an **evidence** tool. It fetches pages with `httpx` (with automatic Crawl4AI browser rendering for JavaScript-heavy pages) and returns a minimal JSON envelope: `stage`, `url`, `requires_analysis`, `workflow`, `agent_guidance`, `next_action`, and the Markdown `content`. The `content` field is raw source material and carries an `agent_guidance` string instructing the model to analyze it and write its own cited answer rather than pasting the content to the user.

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

One tool, two input modes: write supplied `content`, or research a `query` online first and write the result. Supported output formats: Markdown (`md`), plain text (`txt`), `pdf`, Word (`doc`/`docx`), and PowerPoint (`ppt`/`pptx`). Legacy `doc`/`ppt` requests are written as modern `.docx`/`.pptx`, which Word and PowerPoint open natively.

Parameters:

- `filename`: output filename or relative path. The extension matching `file_type` is appended when omitted.
- `content`: ready-made Markdown-like content to write. Leave empty when using `query`.
- `query`: research question to answer with web research; the researched answer is written to the file. Leave empty when using `content`.
- `search_mode`: research pipeline used when `query` is set: `smart` runs a fast single-pass `smart_search` summary; `deep` runs the iterative `deep_research` report. Default: `smart`.
- `file_type`: output type: `md`/`markdown`, `txt`, `pdf`, `doc`/`docx`, or `ppt`/`pptx`. A matching filename extension also selects the type. Default: `md`.
- `overwrite`: replace an existing file at the target path. Default: `false`.
- `write_mode`: `write` creates/replaces content, `append` adds the content as a chunk (Markdown and text files only). Default: `write`.
- `max_sources`: maximum web sources to use in query mode. `0` uses the search mode's default. Default: `0`.
- `time_range`: optional SearXNG time range for query mode: `day`, `month`, or `year`.
- `model`: optional model override for the configured LLM provider in query mode.
- `min_words`: minimum word count required for supplied `content`. Use `700`-`1200` for 2-3 page reports, or `0` for short notes. Ignored in query mode. Default: `0`.
- `ensure_trailing_newline`: append a trailing newline to non-empty Markdown/text content. Ignored for binary output. Default: `true`.

Provide exactly one of `content` or `query`; the tool errors when both or neither is set. Query mode requires the same LLM backend as `smart_search`/`deep_research` (local Ollama by default, or Gemini via `LLM_PROVIDER=gemini`).

The response reports the generated file path, write mode, byte count, character count, and whether an existing file was overwritten (plus the query and search mode in query mode). PDF, Word, and PowerPoint output are rendered from Markdown-like text. `append`/chunk mode is supported for Markdown and text only; generate binary formats with `write_mode="write"` and the complete content.

For large Markdown/text files, call `generate_file` once with `write_mode="write"` for the first chunk, then call it again with `write_mode="append"` for later chunks.

You must define a download location in `.env`; otherwise file-writing tools return `Download path not defined`.

```env
LOCAL_MCP_FILE_OUTPUT_DIR=D:\Downloads\local-mcp
```

### `run_agent_team`, `define_agent_team`, `list_agent_teams`, `delete_agent_team`

Sub-agent orchestration: run a small team of role-based agents (2-3 roles work best on a local model) sequentially on one task. Each agent has its own system-prompt role and an optional tool allowlist (`web_search`, `web_fetch`, `extract_urls`, `parse_document`); a tool-using agent runs as a **LangGraph ReAct agent** over `ChatOllama`, reasoning and calling its allowed tools before writing a hand-off. Each agent reads the task plus the previous agents' hand-offs, and the last agent's message is the team's final answer.

The LangGraph engine is an optional extra — install it with `pip install "local-mcp[agents-langgraph]"`. Without it, text-only and no-tools teams still run, but `run_agent_team` errors with that install hint for any agent that needs its tools.

Two presets ship built in — `research` (researcher + writer) and `research-review` (adds a fact-checking reviewer) — and `define_agent_team` saves custom teams as JSON files under `LOCAL_MCP_AGENT_TEAM_DIR` (default `.tmp/agent_teams`). Uses the same pluggable LLM backend as `smart_search` (local Ollama by default; with `LLM_PROVIDER=gemini` agents run text-only, since tool calling requires Ollama). The simple tool profile exposes a one-call wrapper, `run_agent_task`. See [`docs/agent_teams.md`](docs/agent_teams.md).

Remember: every agent is another call into the *same* local model, so agents serialize — a 3-role team costs roughly 3x (plus tool calls) the time of a single prompt.
