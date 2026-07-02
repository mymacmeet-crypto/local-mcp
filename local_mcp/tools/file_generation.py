"""MCP tool handler for file generation."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from local_mcp.file_generation import write_generated_file
from local_mcp.shared.errors import tool_error


async def generate_file(
    filename: Annotated[
        str,
        Field(
            description=(
                "Output Markdown filename or relative path. The .md extension is appended when omitted."
            ),
        ),
    ],
    content: Annotated[
        str,
        Field(description="Markdown content to write into the generated file."),
    ],
    file_type: Annotated[
        str,
        Field(description="Output file type. MVP supports only md/markdown."),
    ] = "md",
    output_dir: Annotated[
        str,
        Field(
            description=(
                "Destination directory. Relative paths resolve from the server working directory. "
                "Empty uses LOCAL_MCP_FILE_OUTPUT_DIR, LOCAL_MCP_DOWNLOAD_DIR, or generated_files."
            ),
        ),
    ] = "",
    overwrite: Annotated[
        bool,
        Field(description="Replace an existing file at the target path."),
    ] = False,
    ensure_trailing_newline: Annotated[
        bool,
        Field(description="Append a trailing newline to non-empty Markdown content."),
    ] = True,
) -> str:
    """Generate a local Markdown file from supplied content."""
    try:
        result = write_generated_file(
            filename,
            content,
            file_type=file_type,
            output_dir=output_dir,
            overwrite=overwrite,
            ensure_trailing_newline=ensure_trailing_newline,
        )
    except Exception as err:
        raise tool_error(str(err))

    return "\n".join(
        [
            "Markdown file generated.",
            f"- Path: {result.path}",
            f"- File type: {result.file_type}",
            f"- Characters written: {result.characters_written}",
            f"- Bytes written: {result.bytes_written}",
            f"- Overwritten: {'yes' if result.overwritten else 'no'}",
        ]
    )
