"""MCP tool handler for unified file generation.

One tool, two input modes:

- `content` — write the supplied Markdown-like text to a local file.
- `query`   — research the question online first (`smart_search` for a fast
  cited summary, `deep_research` for an iterative long-form report) and write
  the result to a local file.

Supported output formats: Markdown (md), plain text (txt), PDF, Word
(doc/docx), and PowerPoint (ppt/pptx).
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from local_mcp.file_generation import GeneratedFile, append_generated_file, write_generated_file
from local_mcp.shared.errors import tool_error
from local_mcp.shared.progress import Progress
from local_mcp.tools import deep_research, smart_search

FileType = Literal["md", "markdown", "txt", "pdf", "doc", "docx", "ppt", "pptx"]
SearchMode = Literal["smart", "deep"]
SearchTimeRange = Literal["", "day", "month", "year"]
WriteMode = Literal["write", "append"]

SMART_MAX_SOURCES_LIMIT = 10
DEEP_MAX_SOURCES_LIMIT = 30

_TYPE_LABELS = {"md": "Markdown", "txt": "Text", "pdf": "PDF", "docx": "Word", "pptx": "PowerPoint"}


async def generate_file(
    filename: Annotated[
        str,
        Field(
            description=(
                "Output filename or relative path. The extension matching file_type is appended when omitted."
            ),
        ),
    ],
    content: Annotated[
        str,
        Field(description="Ready-made Markdown-like content to write. Leave empty when using `query`."),
    ] = "",
    query: Annotated[
        str,
        Field(
            description=(
                "Research question to answer with web research; the researched answer is written to the file. "
                "Leave empty when using `content`."
            ),
        ),
    ] = "",
    search_mode: Annotated[
        SearchMode,
        Field(
            description=(
                "Research pipeline used when `query` is set: `smart` runs a fast single-pass smart_search "
                "summary; `deep` runs the iterative deep_research report (slower, more thorough)."
            ),
        ),
    ] = "smart",
    file_type: Annotated[
        FileType,
        Field(
            description=(
                "Output file type: md/markdown, txt, pdf, doc/docx (Word), or ppt/pptx (PowerPoint). "
                "A matching filename extension also selects the type. doc/ppt are written as modern .docx/.pptx."
            ),
        ),
    ] = "md",
    overwrite: Annotated[
        bool,
        Field(description="Replace an existing file at the target path."),
    ] = False,
    write_mode: Annotated[
        WriteMode,
        Field(
            description=(
                "`write` creates/replaces the file; `append` adds this content as a chunk "
                "(Markdown and text files only)."
            ),
        ),
    ] = "write",
    max_sources: Annotated[
        int,
        Field(
            description="Maximum web sources to use in query mode. 0 uses the search mode's default.",
            ge=0,
            le=DEEP_MAX_SOURCES_LIMIT,
        ),
    ] = 0,
    time_range: Annotated[
        SearchTimeRange,
        Field(description="Optional SearXNG time range for query mode: `day`, `month`, or `year`. Empty means any time."),
    ] = "",
    model: Annotated[
        str,
        Field(description="Optional model override for the configured LLM provider in query mode. Empty uses the provider default."),
    ] = "",
    min_words: Annotated[
        int,
        Field(
            description=(
                "Minimum word count required for supplied `content` before writing. Use 700-1200 for a "
                "2-3 page report, 0 to allow short notes. Ignored in query mode."
            ),
            ge=0,
            le=20000,
        ),
    ] = 0,
    ensure_trailing_newline: Annotated[
        bool,
        Field(description="Append a trailing newline to non-empty Markdown/text content. Ignored for binary output."),
    ] = True,
    ctx: Context | None = None,
) -> str:
    """Generate a local md/txt/pdf/docx/pptx file from supplied content or from web research.

    Provide exactly one of `content` or `query`. With `content`, the supplied text is
    written as-is. With `query`, the question is researched online first (`search_mode`
    `smart` for a fast cited summary, `deep` for an iterative research report) and the
    result is written to the file.
    """
    has_content = bool(content.strip())
    has_query = bool(query.strip())
    if has_content == has_query:
        raise tool_error(
            "Provide exactly one of `content` or `query`: use `content` to write supplied text, "
            "or `query` to research the topic online and write the answer."
        )

    progress = Progress(ctx)
    if has_query:
        # The research sub-tool streams its own detailed progress via ``ctx``.
        document = await _research_content(
            query.strip(),
            search_mode=search_mode,
            max_sources=max_sources,
            time_range=time_range,
            model=model,
            ctx=ctx,
        )
    else:
        try:
            _validate_min_words(content, min_words)
        except ValueError as err:
            raise tool_error(str(err))
        document = content

    await progress.report(f"Writing {file_type} file to {filename}...")
    try:
        result = _write_content_to_file(
            filename,
            document,
            file_type=file_type,
            overwrite=overwrite,
            write_mode=write_mode,
            ensure_trailing_newline=ensure_trailing_newline,
        )
    except Exception as err:
        raise tool_error(str(err))

    return _format_generated_file_result(
        result,
        query=query.strip() if has_query else "",
        search_mode=search_mode if has_query else "",
    )


async def _research_content(
    query: str,
    *,
    search_mode: str,
    max_sources: int,
    time_range: str,
    model: str,
    ctx: Context | None = None,
) -> str:
    mode = _normalize_search_mode(search_mode)
    if mode == "deep":
        kwargs = {"max_sources": min(max_sources, DEEP_MAX_SOURCES_LIMIT)} if max_sources > 0 else {}
        return await deep_research.deep_research(query, time_range=time_range, model=model, ctx=ctx, **kwargs)

    kwargs = {"max_sources": min(max_sources, SMART_MAX_SOURCES_LIMIT)} if max_sources > 0 else {}
    summary = await smart_search.smart_search(query, time_range=time_range, model=model, ctx=ctx, **kwargs)
    return f"# {query}\n\n{summary}"


def _normalize_search_mode(search_mode: str) -> str:
    normalized = (search_mode or "smart").strip().lower().replace("-", "_")
    if normalized in {"smart", "smart_search"}:
        return "smart"
    if normalized in {"deep", "deep_research", "deep_search"}:
        return "deep"
    raise tool_error("search_mode must be 'smart' or 'deep'.")


def _write_content_to_file(
    filename: str,
    content: str,
    *,
    file_type: str,
    overwrite: bool,
    write_mode: str,
    ensure_trailing_newline: bool,
    infer_file_type_from_filename: bool = True,
) -> GeneratedFile:
    normalized_mode = _normalize_write_mode(write_mode)
    if normalized_mode == "append":
        if overwrite:
            raise ValueError("overwrite is only supported with write_mode='write'.")
        return append_generated_file(
            filename,
            content,
            file_type=file_type,
            ensure_trailing_newline=ensure_trailing_newline,
            infer_file_type_from_filename=infer_file_type_from_filename,
        )

    return write_generated_file(
        filename,
        content,
        file_type=file_type,
        overwrite=overwrite,
        ensure_trailing_newline=ensure_trailing_newline,
        infer_file_type_from_filename=infer_file_type_from_filename,
    )


def _normalize_write_mode(write_mode: str) -> str:
    normalized = (write_mode or "write").strip().lower()
    if normalized == "chunk":
        return "append"
    if normalized not in {"write", "append"}:
        raise ValueError("write_mode must be 'write' or 'append'.")
    return normalized


def _validate_min_words(content: str, min_words: int) -> None:
    if min_words <= 0:
        return
    words = _word_count(content)
    if words >= min_words:
        return
    raise ValueError(
        f"Content is too short for this file: {words} words provided, but at least {min_words} words are required. "
        "Expand the content with fuller sections, examples, details, and a conclusion, then call the file tool again."
    )


def _word_count(content: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", content or ""))


def _format_generated_file_result(result: GeneratedFile, *, query: str = "", search_mode: str = "") -> str:
    label = _TYPE_LABELS.get(result.file_type, result.file_type)
    message = f"{label} file appended." if result.operation == "append" else f"{label} file generated."
    lines = [message]
    if query:
        lines.append(f"- Query: {query}")
        lines.append(f"- Search mode: {search_mode}")
    lines.extend(
        [
            f"- Path: {result.path}",
            f"- File type: {result.file_type}",
            f"- Write mode: {result.operation}",
            f"- Characters written: {result.characters_written}",
            f"- Bytes written: {result.bytes_written}",
            f"- Overwritten: {'yes' if result.overwritten else 'no'}",
        ]
    )
    return "\n".join(lines)
