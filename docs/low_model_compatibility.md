# Low Model Compatibility Improvements

This guide explains the changes made to make `local-mcp` work better with smaller local models such as Qwen-class models.

## Problem

The same MCP tools worked well with Claude but produced weaker results with Qwen. The main symptoms were:

- Qwen called file-writing tools with very short content.
- Markdown or PDF outputs were often only half a page.
- Qwen sometimes stopped after `web_search` and did not call `web_fetch` or `web_summarize`.
- The full tool list exposed many optional arguments, which made tool selection harder for smaller models.

This was not mainly a PDF rendering problem. The file generator writes the content it receives. Claude usually creates a fuller draft before calling the file tool; Qwen often sends a shorter draft.

## What Changed

### 1. Simple Tool Profile

A new tool profile was added for smaller models:

```env
LOCAL_MCP_TOOL_PROFILE=simple
```

The simple profile exposes fewer, clearer tools:

| Tool | Purpose |
| --- | --- |
| `search_web` | Search and automatically summarize fetched result pages. |
| `summarize_web` | Summarize a query or list of URLs. |
| `fetch_web_page` | Fetch one page as Markdown. |
| `list_page_urls` | Extract links from a page or site. |
| `read_document` | Parse a document with safe defaults. |
| `read_image_text` | Run OCR with default English settings. |
| `write_markdown_file` | Write normal Markdown notes. |
| `write_report_file` | Write a longer report and reject short content. |
| `search_web_to_file` | Search and write results directly to a file. |
| `create_scheduled_command` | Create cron files for a recurring command without installing them. |

This reduces the number of choices the model must make.

### 2. Automatic Search Follow-Up

`web_search` can now automatically fetch after search. Enable it with:

```env
LOCAL_MCP_WEB_SEARCH_FOLLOW_UP=summarize
LOCAL_MCP_WEB_SEARCH_FOLLOW_UP_LIMIT=3
```

With this setting, a `web_search` call returns normal search results and then appends summaries from the top fetched pages.

Supported modes:

| Value | Behavior |
| --- | --- |
| `summarize` | Search, then fetch and summarize the top results with `web_summarize`. |
| `fetch_first` | Search, then fetch only the first result with `web_fetch`. |
| `none` | Search results only. |

This helps Qwen because it does not need to remember a second tool call.

### 3. Better Schemas For Tool Arguments

Several free-form string parameters were changed to enum-like `Literal` types. This makes tool schemas clearer for clients and models.

Examples:

- `render`: `auto`, `static`, `browser`
- `output_format`: `markdown`, `text`, `html`, `json`
- `parser`: `auto`, `pypdf`, `pymupdf4llm`, `pdfplumber`, `docling`, `marker`, `mineru`, `text`
- `file_type`: `md`, `markdown`, `pdf`
- `write_mode`: `write`, `append`
- `scheduler`: `cron`, `launchd`, `n8n`

Smaller models usually do better when valid choices are explicit.

### 4. Minimum Content Guard

`generate_file` now supports:

```text
min_words
```

When `min_words` is greater than `0`, the tool refuses to write content that is too short. This prevents short, low-quality files from being silently generated.

The simple profile also adds `write_report_file`, which defaults to a longer report requirement:

```text
min_words=900
```

Use `write_markdown_file` for short notes. Use `write_report_file` only when you expect a full report.

## Recommended Configuration

For Qwen or another smaller local model, use:

```env
LOCAL_MCP_FILE_OUTPUT_DIR=generated_files
LOCAL_MCP_TOOL_PROFILE=simple
LOCAL_MCP_WEB_SEARCH_FOLLOW_UP=summarize
LOCAL_MCP_WEB_SEARCH_FOLLOW_UP_LIMIT=3
```

Restart the MCP server after changing `.env`.

## Recommended Prompt Pattern

For normal answer generation:

```text
Using local-mcp, search the web for "local LLM MCP tool calling" and return a detailed answer using the fetched summaries.
```

For Markdown notes:

```text
Using local-mcp, search the web for "local LLM MCP tool calling", use the fetched summaries, and write detailed Markdown notes with write_markdown_file named reports/mcp-tool-calling-notes.md.
```

For a long report:

```text
Using local-mcp, search the web for "local LLM MCP tool calling", use the fetched summaries, and write a detailed report with write_report_file named reports/mcp-tool-calling-report.md with file_type=md and min_words=900.
```

## How The Improved Flow Works

With the recommended settings, the flow becomes:

```text
User asks question
  -> model calls search_web or web_search
  -> server searches SearXNG
  -> server fetches/summarizes top result pages
  -> model receives richer source-backed context
  -> model answers or writes a file
  -> file tool rejects too-short report content when min_words is set
```

The server now carries more of the workflow, so the model has fewer chances to skip important steps.

## Testing

Run the test suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover tests
```

Expected result:

```text
OK
```

Useful manual test:

```text
Using local-mcp, search the web for "MCP server tool calling best practices" and return a detailed answer using the fetched summaries.
```

The response should include fetched or summarized source content, not only short search snippets.

## Troubleshooting

### The response still only contains search snippets

Check `.env`:

```env
LOCAL_MCP_WEB_SEARCH_FOLLOW_UP=summarize
```

Then restart the MCP server.

### The model still chooses the wrong tool

Use the simple profile:

```env
LOCAL_MCP_TOOL_PROFILE=simple
```

Then restart the MCP server.

### The generated file is still too short

Use `write_report_file` or set `min_words` on `generate_file`.

Example:

```text
Use write_report_file with min_words=900.
```

### Browser-rendered pages are missing content

Install the optional browser support:

```powershell
python -m pip install ".[browser]"
crawl4ai-setup
```

Then retry with `render=auto` or `render=browser`.

## Changed Files

Main implementation files:

- [`local_mcp/tools/__init__.py`](../local_mcp/tools/__init__.py)
- [`local_mcp/tools/simple.py`](../local_mcp/tools/simple.py)
- [`local_mcp/tools/search.py`](../local_mcp/tools/search.py)
- [`local_mcp/tools/file_generation.py`](../local_mcp/tools/file_generation.py)
- [`local_mcp/tools/web.py`](../local_mcp/tools/web.py)
- [`local_mcp/tools/documents.py`](../local_mcp/tools/documents.py)

Tests:

- [`tests/test_compatibility_imports.py`](../tests/test_compatibility_imports.py)
- [`tests/test_file_generation.py`](../tests/test_file_generation.py)
- [`tests/test_search_helpers.py`](../tests/test_search_helpers.py)
