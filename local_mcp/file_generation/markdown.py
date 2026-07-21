"""Generated file service for Markdown, text, PDF, Word, and PowerPoint outputs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from local_mcp.file_generation.pdf import default_pdf_title, render_text_pdf

# Accepted `file_type` values. Legacy Office types map to their OOXML successors:
# doc -> docx, ppt -> pptx (real binary .doc/.ppt output is not supported).
CANONICAL_FILE_TYPES = {
    "md": "md",
    "markdown": "md",
    "txt": "txt",
    "pdf": "pdf",
    "doc": "docx",
    "docx": "docx",
    "ppt": "pptx",
    "pptx": "pptx",
}
SUPPORTED_FILE_TYPES = set(CANONICAL_FILE_TYPES)
TYPE_SUFFIXES = {"md": ".md", "txt": ".txt", "pdf": ".pdf", "docx": ".docx", "pptx": ".pptx"}
SUFFIX_TYPES = {
    ".md": "md",
    ".markdown": "md",
    ".txt": "txt",
    ".pdf": "pdf",
    ".doc": "docx",
    ".docx": "docx",
    ".ppt": "pptx",
    ".pptx": "pptx",
}
# Binary formats are rendered from the complete content in one pass.
NON_APPENDABLE_TYPES = {"pdf", "docx", "pptx"}
OUTPUT_DIR_ENV = "LOCAL_MCP_FILE_OUTPUT_DIR"
DOWNLOAD_DIR_ENV = "LOCAL_MCP_DOWNLOAD_DIR"


@dataclass(frozen=True)
class GeneratedFile:
    path: Path
    file_type: str
    characters_written: int
    bytes_written: int
    overwritten: bool
    operation: str = "write"


def write_generated_file(
    filename: str,
    content: str,
    *,
    file_type: str = "md",
    overwrite: bool = False,
    ensure_trailing_newline: bool = True,
    infer_file_type_from_filename: bool = True,
) -> GeneratedFile:
    """Write generated content to a safe output path."""
    normalized_type = _normalize_file_type(
        file_type,
        filename,
        infer_file_type_from_filename=infer_file_type_from_filename,
    )
    target = _resolve_output_path(filename, normalized_type)
    existed = target.exists()
    if existed and not overwrite:
        raise ValueError(f"{target} already exists. Set overwrite=true to replace it.")

    target.parent.mkdir(parents=True, exist_ok=True)
    if normalized_type == "pdf":
        source_content = content or ""
        pdf_bytes = render_text_pdf(source_content, title=default_pdf_title(target))
        target.write_bytes(pdf_bytes)
        characters_written = len(source_content)
        bytes_written = len(pdf_bytes)
    elif normalized_type == "docx":
        from local_mcp.file_generation.word import render_docx_file

        source_content = content or ""
        bytes_written = render_docx_file(source_content, target, title=default_pdf_title(target))
        characters_written = len(source_content)
    elif normalized_type == "pptx":
        from local_mcp.file_generation.powerpoint import render_pptx_file

        source_content = content or ""
        bytes_written = render_pptx_file(source_content, target, title=default_pdf_title(target))
        characters_written = len(source_content)
    else:
        final_content = _prepare_content(content, ensure_trailing_newline=ensure_trailing_newline)
        target.write_text(final_content, encoding="utf-8", newline="\n")
        characters_written = len(final_content)
        bytes_written = len(final_content.encode("utf-8"))

    return GeneratedFile(
        path=target,
        file_type=normalized_type,
        characters_written=characters_written,
        bytes_written=bytes_written,
        overwritten=existed,
        operation="write",
    )


def append_generated_file(
    filename: str,
    content: str,
    *,
    file_type: str = "md",
    ensure_trailing_newline: bool = True,
    infer_file_type_from_filename: bool = True,
) -> GeneratedFile:
    """Append a Markdown content chunk to a safe output path."""
    normalized_type = _normalize_file_type(
        file_type,
        filename,
        infer_file_type_from_filename=infer_file_type_from_filename,
    )
    if normalized_type in NON_APPENDABLE_TYPES:
        raise ValueError(
            f"Appending to {normalized_type.upper()} output is not supported. "
            "Use write_mode='write' with the complete content."
        )
    target = _resolve_output_path(filename, normalized_type)

    final_content = _prepare_content(content, ensure_trailing_newline=ensure_trailing_newline)

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as file:
        file.write(final_content)

    return GeneratedFile(
        path=target,
        file_type=normalized_type,
        characters_written=len(final_content),
        bytes_written=len(final_content.encode("utf-8")),
        overwritten=False,
        operation="append",
    )


def _normalize_file_type(
    file_type: str,
    filename: str = "",
    *,
    infer_file_type_from_filename: bool = True,
) -> str:
    normalized = (file_type or "md").strip().lower().lstrip(".")
    if normalized not in SUPPORTED_FILE_TYPES:
        raise ValueError("file_type must be one of: md, markdown, txt, pdf, doc, docx, ppt, pptx.")
    canonical = CANONICAL_FILE_TYPES[normalized]
    if infer_file_type_from_filename and canonical == "md":
        suffix_type = SUFFIX_TYPES.get(_filename_suffix(filename))
        if suffix_type:
            return suffix_type
    return canonical


def _prepare_content(content: str, *, ensure_trailing_newline: bool) -> str:
    final_content = content or ""
    if ensure_trailing_newline and final_content and not final_content.endswith("\n"):
        final_content += "\n"
    return final_content


def _resolve_output_path(filename: str, file_type: str) -> Path:
    clean_filename = (filename or "").strip().strip("\"'")
    if not clean_filename:
        raise ValueError("filename is required.")
    if "\x00" in clean_filename:
        raise ValueError("filename cannot contain null bytes.")

    requested = Path(clean_filename)
    if requested.is_absolute() or requested.drive:
        raise ValueError(f"filename must be relative. Set {OUTPUT_DIR_ENV} or {DOWNLOAD_DIR_ENV} to choose the destination folder.")
    if any(part == ".." for part in requested.parts):
        raise ValueError("filename cannot contain '..' path segments.")

    expected_suffix = TYPE_SUFFIXES[file_type]
    if requested.suffix and SUFFIX_TYPES.get(requested.suffix.lower()) != file_type:
        raise ValueError(f"filename suffix must match file_type '{file_type}' ({expected_suffix}).")
    # Also normalizes legacy suffixes to the written format (.doc -> .docx, .ppt -> .pptx).
    requested = requested.with_suffix(expected_suffix)

    root = Path(_configured_output_dir()).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root

    root = root.resolve()
    target = (root / requested).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Resolved output path must stay inside the configured download path.")
    return target


def _filename_suffix(filename: str) -> str:
    clean_filename = (filename or "").strip().strip("\"'")
    if not clean_filename or "\x00" in clean_filename:
        return ""
    return Path(clean_filename).suffix.lower()


def _configured_output_dir() -> str:
    configured = (os.environ.get(OUTPUT_DIR_ENV) or os.environ.get(DOWNLOAD_DIR_ENV) or "").strip()
    if not configured:
        raise ValueError(f"Download path not defined. Set {OUTPUT_DIR_ENV} or {DOWNLOAD_DIR_ENV} in .env.")
    return configured
