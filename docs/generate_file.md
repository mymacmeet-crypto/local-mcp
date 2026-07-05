# `generate_file`

Generate a local Markdown or PDF file from supplied content.

The tool accepts `md`/`markdown` and `pdf` as `file_type`. A `.pdf` filename also selects PDF output.

Use `write_mode="append"` to build larger Markdown files in chunks when a smaller AI model cannot provide the whole document in one tool call. PDF output must be generated with `write_mode="write"` and the complete content.

## How It Works

```mermaid
flowchart TD
    A[MCP client calls generate_file] --> B[Validate file_type]
    B -->|md, markdown, or pdf| C[Normalize filename]
    B -->|other type| X[Return tool error]
    C --> D[Reject absolute paths and .. segments]
    D --> E[Append .md or .pdf when extension is missing]
    E --> F[Resolve env download path]
    F --> G[Ensure target stays inside configured path]
    G --> H{write_mode?}
    H -->|write| I{File exists?}
    I -->|yes, overwrite=false| Y[Return tool error]
    I -->|no or overwrite=true| J[Create parent directories]
    H -->|append/chunk and md| J
    H -->|append/chunk and pdf| Z[Return tool error]
    J --> K[Write or append UTF-8 Markdown, or write PDF bytes]
    K --> L[Return path, byte count, character count, overwrite status]
```

## Parameters

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `filename` | string | required | Output Markdown or PDF filename or relative path. The matching extension is appended when omitted. |
| `content` | string | required | Markdown-like content to write. |
| `file_type` | string | `md` | Output file type. Supports `md`/`markdown` and `pdf`. A `.pdf` filename also selects PDF output. |
| `overwrite` | boolean | `false` | Replace an existing file at the target path. |
| `write_mode` | string | `write` | `write` creates/replaces content. `append` adds Markdown content as a chunk. `chunk` is accepted as an alias for `append`. |
| `ensure_trailing_newline` | boolean | `true` | Append a trailing newline to non-empty Markdown content. Ignored for PDF output. |

## Path Behavior

- `filename` must be relative.
- The destination folder must be configured with `LOCAL_MCP_FILE_OUTPUT_DIR` or `LOCAL_MCP_DOWNLOAD_DIR`.
- `..` path segments are rejected.
- Parent directories are created automatically.
- Existing files are preserved unless `overwrite` is `true`.
- `append` mode creates Markdown files if they do not exist and never overwrites existing content.
- PDF output supports `write` mode only.
- Only `.md` and `.pdf` output files are accepted.

## Download Location

Set the download location in `.env`:

```env
LOCAL_MCP_FILE_OUTPUT_DIR=~/Downloads/local-mcp
```

`LOCAL_MCP_DOWNLOAD_DIR` is also supported as a friendlier alias. Precedence is:

```text
LOCAL_MCP_FILE_OUTPUT_DIR -> LOCAL_MCP_DOWNLOAD_DIR
```

If neither environment variable is set, the tool returns:

```text
Download path not defined. Set LOCAL_MCP_FILE_OUTPUT_DIR or LOCAL_MCP_DOWNLOAD_DIR in .env.
```

## Example

```json
{
  "filename": "notes/project-brief",
  "content": "# Project Brief\n\n- Owner: Local MCP\n- Status: MVP\n",
  "file_type": "md"
}
```

With `LOCAL_MCP_FILE_OUTPUT_DIR=~/Downloads/local-mcp`, this creates:

```text
~/Downloads/local-mcp/notes/project-brief.md
```

## PDF Example

```json
{
  "filename": "reports/project-brief.pdf",
  "content": "# Project Brief\n\n- Owner: Local MCP\n- Status: PDF-ready\n"
}
```

With `LOCAL_MCP_FILE_OUTPUT_DIR=~/Downloads/local-mcp`, this creates:

```text
~/Downloads/local-mcp/reports/project-brief.pdf
```

## Chunked Example

First chunk:

```json
{
  "filename": "reports/large-report",
  "content": "# Large Report\n\nFirst section...",
  "write_mode": "write",
  "overwrite": true
}
```

Later chunks:

```json
{
  "filename": "reports/large-report",
  "content": "Next section...",
  "write_mode": "append"
}
```
