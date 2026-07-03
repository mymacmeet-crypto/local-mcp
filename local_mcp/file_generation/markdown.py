"""Markdown file generation service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_FILE_TYPES = {"md", "markdown"}
OUTPUT_DIR_ENV = "LOCAL_MCP_FILE_OUTPUT_DIR"
DOWNLOAD_DIR_ENV = "LOCAL_MCP_DOWNLOAD_DIR"


@dataclass(frozen=True)
class GeneratedFile:
    path: Path
    file_type: str
    characters_written: int
    bytes_written: int
    overwritten: bool


def write_generated_file(
    filename: str,
    content: str,
    *,
    file_type: str = "md",
    overwrite: bool = False,
    ensure_trailing_newline: bool = True,
) -> GeneratedFile:
    """Write Markdown content to a safe output path."""
    normalized_type = _normalize_file_type(file_type)
    target = _resolve_output_path(filename)
    existed = target.exists()
    if existed and not overwrite:
        raise ValueError(f"{target} already exists. Set overwrite=true to replace it.")

    final_content = content or ""
    if ensure_trailing_newline and final_content and not final_content.endswith("\n"):
        final_content += "\n"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(final_content, encoding="utf-8", newline="\n")

    return GeneratedFile(
        path=target,
        file_type=normalized_type,
        characters_written=len(final_content),
        bytes_written=len(final_content.encode("utf-8")),
        overwritten=existed,
    )


def _normalize_file_type(file_type: str) -> str:
    normalized = (file_type or "md").strip().lower().lstrip(".")
    if normalized not in SUPPORTED_FILE_TYPES:
        raise ValueError("MVP file generation supports only Markdown files: file_type must be 'md'.")
    return "md"


def _resolve_output_path(filename: str) -> Path:
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

    if requested.suffix:
        if requested.suffix.lower() != ".md":
            raise ValueError("MVP file generation only supports .md output files.")
    else:
        requested = requested.with_suffix(".md")

    root = Path(_configured_output_dir()).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root

    root = root.resolve()
    target = (root / requested).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Resolved output path must stay inside the configured download path.")
    return target


def _configured_output_dir() -> str:
    configured = (os.environ.get(OUTPUT_DIR_ENV) or os.environ.get(DOWNLOAD_DIR_ENV) or "").strip()
    if not configured:
        raise ValueError(f"Download path not defined. Set {OUTPUT_DIR_ENV} or {DOWNLOAD_DIR_ENV} in .env.")
    return configured
