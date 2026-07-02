# `generate_file`

Generate a local Markdown file from supplied content.

The MVP intentionally supports only Markdown output. The tool accepts `md` or `markdown` as `file_type`; docx, xlsx, pptx, and pdf can be added later behind the same interface.

## How It Works

```mermaid
flowchart TD
    A[MCP client calls generate_file] --> B[Validate file_type]
    B -->|md or markdown| C[Normalize filename]
    B -->|other type| X[Return tool error]
    C --> D[Reject absolute paths and .. segments]
    D --> E[Append .md when extension is missing]
    E --> F[Resolve output_dir or env default]
    F --> G[Ensure target stays inside output_dir]
    G --> H{File exists?}
    H -->|yes, overwrite=false| Y[Return tool error]
    H -->|no or overwrite=true| I[Create parent directories]
    I --> J[Write UTF-8 Markdown]
    J --> K[Return path, byte count, character count, overwrite status]
```

## Parameters

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `filename` | string | required | Output Markdown filename or relative path. The `.md` extension is appended when omitted. |
| `content` | string | required | Markdown content to write. |
| `file_type` | string | `md` | Output file type. MVP supports only `md`/`markdown`. |
| `output_dir` | string | empty | Destination directory. Relative paths resolve from the server working directory. Empty uses `LOCAL_MCP_FILE_OUTPUT_DIR`, `LOCAL_MCP_DOWNLOAD_DIR`, or `generated_files`. |
| `overwrite` | boolean | `false` | Replace an existing file at the target path. |
| `ensure_trailing_newline` | boolean | `true` | Append a trailing newline to non-empty Markdown content. |

## Path Behavior

- `filename` must be relative; use `output_dir` to choose the destination folder.
- `..` path segments are rejected.
- Parent directories are created automatically.
- Existing files are preserved unless `overwrite` is `true`.
- Only `.md` output files are accepted for the MVP.

## Download Location

Users can choose the download location per call with `output_dir`:

```json
{
  "filename": "notes/project-brief",
  "content": "# Project Brief\n",
  "output_dir": "D:\\MCP\\local-mcp\\generated_files"
}
```

Or set a default location in `.env`:

```env
LOCAL_MCP_FILE_OUTPUT_DIR=~/Downloads/local-mcp
```

`LOCAL_MCP_DOWNLOAD_DIR` is also supported as a friendlier alias. Precedence is:

```text
output_dir argument -> LOCAL_MCP_FILE_OUTPUT_DIR -> LOCAL_MCP_DOWNLOAD_DIR -> generated_files
```

## Example

```json
{
  "filename": "notes/project-brief",
  "content": "# Project Brief\n\n- Owner: Local MCP\n- Status: MVP\n",
  "file_type": "md"
}
```

With the default configuration, this creates:

```text
generated_files/notes/project-brief.md
```
