# `generate_file`

Generate or append to a local Markdown file from supplied content.

The MVP intentionally supports only Markdown output. The tool accepts `md` or `markdown` as `file_type`; docx, xlsx, pptx, and pdf can be added later behind the same interface.

Use `write_mode="append"` to build larger files in chunks when a smaller AI model cannot provide the whole document in one tool call.

## How It Works

```mermaid
flowchart TD
    A[MCP client calls generate_file] --> B[Validate file_type]
    B -->|md or markdown| C[Normalize filename]
    B -->|other type| X[Return tool error]
    C --> D[Reject absolute paths and .. segments]
    D --> E[Append .md when extension is missing]
    E --> F[Resolve env download path]
    F --> G[Ensure target stays inside configured path]
    G --> H{write_mode?}
    H -->|write| I{File exists?}
    I -->|yes, overwrite=false| Y[Return tool error]
    I -->|no or overwrite=true| J[Create parent directories]
    H -->|append/chunk| J
    J --> K[Write or append UTF-8 Markdown]
    K --> L[Return path, byte count, character count, overwrite status]
```

## Parameters

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `filename` | string | required | Output Markdown filename or relative path. The `.md` extension is appended when omitted. |
| `content` | string | required | Markdown content to write. |
| `file_type` | string | `md` | Output file type. MVP supports only `md`/`markdown`. |
| `overwrite` | boolean | `false` | Replace an existing file at the target path. |
| `write_mode` | string | `write` | `write` creates/replaces content. `append` adds the content as a chunk. `chunk` is accepted as an alias for `append`. |
| `ensure_trailing_newline` | boolean | `true` | Append a trailing newline to non-empty Markdown content. |

## Path Behavior

- `filename` must be relative.
- The destination folder must be configured with `LOCAL_MCP_FILE_OUTPUT_DIR` or `LOCAL_MCP_DOWNLOAD_DIR`.
- `..` path segments are rejected.
- Parent directories are created automatically.
- Existing files are preserved unless `overwrite` is `true`.
- `append` mode creates the file if it does not exist and never overwrites existing content.
- Only `.md` output files are accepted for the MVP.

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
