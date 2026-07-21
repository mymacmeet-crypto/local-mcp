# Low Model Compatibility Improvements

This guide explains the changes made to make `local-mcp` work better with smaller local models such as Qwen-class models.

## Problem

The same MCP tools worked well with Claude but produced weaker results with Qwen. The main symptoms were:

- Qwen called file-writing tools with very short content.
- Markdown or PDF outputs were often only half a page.
- Qwen sometimes stopped after `web_search` and did not call `web_fetch`.
- Qwen pasted raw search snippets or raw fetched markdown to the user as if they were a final answer.
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
| `fetch_web_page` | Fetch one page as Markdown. |
| `list_page_urls` | Extract links from a page or site. |
| `read_document` | Parse a document with safe defaults. |
| `read_image_text` | Run OCR with default English settings. |
| `generate_file` | Write a file from supplied content, or research a query and write the answer. |
| `create_scheduled_command` | Create and install a recurring scheduled command (overwrites existing files for the same name). |
| `list_scheduled_commands` | List scheduled commands and whether each is installed. |
| `remove_scheduled_command` | Uninstall a scheduled command and delete its generated files. |

This reduces the number of choices the model must make.

### 2. Discovery / Evidence Framing

The web tools now describe an explicit two-step research workflow and encode it in both their descriptions and their outputs:

```text
web_search (discover sources) -> web_fetch (read evidence) -> analyze -> write a cited answer
```

- `web_search` is a **discovery** tool. It returns a minimal JSON envelope with a `urls` list, `requires_fetch: true`, and `agent_guidance`/`next_action` strings telling the model that the URLs are not sufficient evidence and that it must call `web_fetch` next.
- `web_fetch` is an **evidence** tool. It returns a minimal JSON envelope with the page `url` and its Markdown `content`, plus `requires_analysis: true` and an `agent_guidance`/`next_action` pair telling the model not to paste the raw content to the user but to synthesize its own cited answer.

This directly counters the two failure modes where Qwen returned raw snippets or raw fetched markdown as if they were the final answer.

### 3. Better Schemas For Tool Arguments

Several free-form string parameters were changed to enum-like `Literal` types. This makes tool schemas clearer for clients and models.

Examples:

- `output_format` (`parse_document`): `markdown`, `text`, `json`
- `parser`: `auto`, `pypdf`, `pymupdf4llm`, `pdfplumber`, `docling`, `marker`, `mineru`, `text`
- `file_type`: `md`, `markdown`, `txt`, `pdf`, `doc`, `docx`, `ppt`, `pptx`
- `write_mode`: `write`, `append`
- `scheduler`: `auto`, `cron`, `launchd`, `systemd`, `n8n`

Smaller models usually do better when valid choices are explicit.

### 4. Minimum Content Guard

`generate_file` now supports:

```text
min_words
```

When `min_words` is greater than `0`, the tool refuses to write content that is too short. This prevents short, low-quality files from being silently generated.

For a full report, ask for a longer requirement explicitly:

```text
min_words=900
```

Use plain `generate_file` for short notes. Set `min_words` only when you expect a full report.

## Recommended Configuration

For Qwen or another smaller local model, use:

```env
LOCAL_MCP_FILE_OUTPUT_DIR=generated_files
LOCAL_MCP_TOOL_PROFILE=simple
```

Restart the MCP server after changing `.env`.

## Recommended Prompt Pattern

For normal answer generation:

```text
Using local-mcp, search the web for "local LLM MCP tool calling" and return a detailed answer using the fetched page content.
```

For Markdown notes:

```text
Using local-mcp, search the web for "local LLM MCP tool calling", use the fetched page content, and write detailed Markdown notes with generate_file named reports/mcp-tool-calling-notes.md.
```

For a long report:

```text
Using local-mcp, search the web for "local LLM MCP tool calling", use the fetched page content, and write a detailed report with generate_file named reports/mcp-tool-calling-report.md with file_type=md and min_words=900.
```

## How The Improved Flow Works

With the recommended settings, the flow becomes:

```text
User asks question
  -> model calls web_search
  -> server searches SearXNG and returns candidate urls
  -> model calls web_fetch on one or more urls (guided by agent_guidance/next_action)
  -> model receives source-backed evidence
  -> model answers or writes a file
  -> file tool rejects too-short report content when min_words is set
```

The tool descriptions and per-response guidance keep the model on the discovery -> evidence -> answer path, so it has fewer chances to skip important steps.

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
Using local-mcp, search the web for "MCP server tool calling best practices" and return a detailed answer using the fetched page content.
```

The response should include fetched source content, not only the raw URL list.

## Troubleshooting

### The response still only contains a URL list

The model stopped after `web_search` instead of calling `web_fetch`. Reinforce the workflow in the prompt (for example, "use the fetched page content"), and confirm the model is honoring the `agent_guidance`/`next_action` fields in the search response.

If a model reliably stops early, prefer the [`smart_search`](smart_search.md) tool instead. It performs the entire search -> rank -> crawl -> summarize chain server-side (using a local Ollama model by default, or Google Gemini if `LLM_PROVIDER=gemini`) and returns a finished, cited answer in one call, so the small model never has to chain `web_search` and `web_fetch` itself. It is part of the `full` tool profile.

### The model still chooses the wrong tool

Use the simple profile:

```env
LOCAL_MCP_TOOL_PROFILE=simple
```

Then restart the MCP server.

### The generated file is still too short

Set `min_words` on `generate_file`.

Example:

```text
Use generate_file with min_words=900.
```

### Browser-rendered pages are missing content

Install the optional browser support:

```powershell
python -m pip install ".[browser]"
crawl4ai-setup
```

Then retry the fetch. `web_fetch` automatically falls back to browser rendering when the static content is thin.

## Changed Files

Main implementation files:

- [`local_mcp/tools/__init__.py`](../local_mcp/tools/__init__.py)
- [`local_mcp/tools/simple.py`](../local_mcp/tools/simple.py)
- [`local_mcp/tools/search.py`](../local_mcp/tools/search.py)
- [`local_mcp/tools/file_generation.py`](../local_mcp/tools/file_generation.py)
- [`local_mcp/tools/web.py`](../local_mcp/tools/web.py)
- [`local_mcp/tools/documents.py`](../local_mcp/tools/documents.py)
- [`local_mcp/shared/guidance.py`](../local_mcp/shared/guidance.py)
- [`local_mcp/shared/summarize.py`](../local_mcp/shared/summarize.py)

Tests:

- [`tests/test_compatibility_imports.py`](../tests/test_compatibility_imports.py)
- [`tests/test_file_generation.py`](../tests/test_file_generation.py)
- [`tests/test_search_helpers.py`](../tests/test_search_helpers.py)
- [`tests/test_summarize_helpers.py`](../tests/test_summarize_helpers.py)
- [`tests/test_web_fetch_tool.py`](../tests/test_web_fetch_tool.py)
