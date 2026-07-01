"""PDF and document parsing helpers."""

from __future__ import annotations

import asyncio
import base64
import binascii
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import ParseResult, unquote, urlparse

import httpx

from errors import describe_fetch_error, tool_error
from fetcher import TIMEOUT_S, USER_AGENT

MAX_DOCUMENT_BYTES = int(os.environ.get("LOCAL_MCP_DOCUMENT_MAX_BYTES", str(100 * 1024 * 1024)))
PARSER_TIMEOUT_S = int(os.environ.get("LOCAL_MCP_DOCUMENT_PARSER_TIMEOUT_S", "900"))
DOCUMENT_TEMP_ROOT = os.environ.get("LOCAL_MCP_DOCUMENT_TMPDIR", "")
BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")
WINDOWS_DRIVE_PATH_RE = re.compile(r"^/[A-Za-z]:([\\/]|$)")
MODULE_DIR = Path(__file__).resolve().parent

PARSERS = {"auto", "pypdf", "pymupdf4llm", "pdfplumber", "docling", "marker", "mineru", "text"}
OUTPUT_FORMATS = {"markdown", "text", "json"}
TEXT_EXTENSIONS = {".csv", ".html", ".json", ".log", ".md", ".rst", ".text", ".txt", ".xml", ".yaml", ".yml"}

INSTALL_HINTS = {
    "pypdf": "Install pypdf with `pip install -r requirements.txt`.",
    "pymupdf4llm": "Install PyMuPDF4LLM with `pip install \".[document-fast]\"` or `pip install pymupdf4llm`.",
    "pdfplumber": "Install pdfplumber with `pip install \".[document-fast]\"` or `pip install pdfplumber`.",
    "docling": "Install Docling with `pip install \".[document-structured]\"` or `pip install docling`.",
    "marker": "Install Marker with `pip install \".[document-deep]\"` or `pip install marker-pdf`.",
    "mineru": "Install MinerU with `pip install \".[document-deep]\"` or `pip install \"mineru[all]\"`.",
}


@dataclass
class DocumentSource:
    path: Path
    label: str
    cleanup_dir: tempfile.TemporaryDirectory[str] | None = None

    def cleanup(self) -> None:
        if self.cleanup_dir is not None:
            self.cleanup_dir.cleanup()


@dataclass
class ParseResult:
    parser: str
    output_format: str
    content: str
    source: str
    metadata: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


async def parse_document(
    document: str,
    *,
    parser: str = "auto",
    output_format: str = "markdown",
    pages: str = "",
    include_metadata: bool = True,
    max_chars: int = 120_000,
) -> str:
    """Parse a document source and return Markdown, text, or JSON."""
    parser_name = _validate_choice(parser, PARSERS, "parser")
    format_name = _validate_choice(output_format, OUTPUT_FORMATS, "output_format")
    source = await _load_document_source(document)
    try:
        result = await asyncio.to_thread(
            _parse_document_path,
            source.path,
            source.label,
            parser_name,
            format_name,
            pages,
        )
    finally:
        source.cleanup()

    return _format_result(result, include_metadata=include_metadata, max_chars=max_chars)


def _parse_document_path(path: Path, source_label: str, parser: str, output_format: str, pages: str) -> ParseResult:
    selected_parser = _choose_auto_parser(path) if parser == "auto" else parser
    if selected_parser == "pypdf":
        return _parse_with_pypdf(path, source_label, output_format, pages)
    if selected_parser == "pymupdf4llm":
        return _parse_with_pymupdf4llm(path, source_label, output_format, pages)
    if selected_parser == "pdfplumber":
        return _parse_with_pdfplumber(path, source_label, output_format, pages)
    if selected_parser == "docling":
        return _parse_with_docling(path, source_label, output_format, pages)
    if selected_parser == "marker":
        return _parse_with_marker(path, source_label, output_format, pages)
    if selected_parser == "mineru":
        return _parse_with_mineru(path, source_label, output_format, pages)
    if selected_parser == "text":
        return _parse_plain_text(path, source_label, output_format, pages)
    raise tool_error(f"Unsupported parser: {selected_parser}")


def _choose_auto_parser(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        for parser in ("pymupdf4llm", "pypdf", "pdfplumber", "docling"):
            if _parser_available(parser):
                return parser
    if suffix in TEXT_EXTENSIONS:
        return "text"
    for parser in ("docling", "marker", "mineru", "pymupdf4llm"):
        if _parser_available(parser):
            return parser
    raise tool_error(
        "No document parser is available for this file. "
        "Install `pypdf` for PDFs or optional document parsers from pyproject extras."
    )


def _parser_available(parser: str) -> bool:
    if parser == "marker":
        return bool(_marker_command())
    if parser == "mineru":
        return bool(_mineru_command())
    if parser == "text":
        return True
    return _has_module(parser)


def _has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


async def _load_document_source(document: str) -> DocumentSource:
    source = _clean_document_source(document)
    if not source:
        raise tool_error("Document path, URL, data URL, or base64 content is required.")

    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        return await _download_document(source)
    if parsed.scheme == "data":
        return _decode_data_url(source)

    local = _local_document_source(source, parsed)
    if local is not None:
        return local

    if _looks_like_base64(source):
        return _bytes_document_source(_decode_base64(source), "document.pdf")

    raise tool_error(f"Document not found or unsupported document source: {source}")


def _clean_document_source(document: str) -> str:
    source = (document or "").strip()
    if len(source) >= 2 and source[0] == source[-1] and source[0] in ("'", '"'):
        return source[1:-1].strip()
    return source


def _local_document_source(source: str, parsed: ParseResult) -> DocumentSource | None:
    for path in _local_path_candidates(source, parsed):
        try:
            if not path.is_file():
                continue
            size = path.stat().st_size
            if size > MAX_DOCUMENT_BYTES:
                raise tool_error(f"Document is too large. Maximum size is {MAX_DOCUMENT_BYTES} bytes.")
            return DocumentSource(path=path, label=str(path))
        except OSError as err:
            raise tool_error(f"Could not read document file: {err}")
    return None


def _local_path_candidates(source: str, parsed: ParseResult) -> list[Path]:
    if parsed.scheme == "file":
        path_source = _file_uri_to_path(parsed)
    else:
        path_source = source

    path = Path(path_source).expanduser()
    candidates = [path]
    if not path.is_absolute():
        candidates.append(Path.cwd() / path)
        candidates.append(MODULE_DIR / path)
    return _unique_paths(candidates)


def _file_uri_to_path(parsed: ParseResult) -> str:
    path = unquote(parsed.path)
    host = unquote(parsed.netloc)

    if os.name == "nt":
        if host and host.lower() != "localhost":
            if re.fullmatch(r"[A-Za-z]:", host):
                path = f"{host}{path}"
            else:
                path = f"//{host}{path}"
        if WINDOWS_DRIVE_PATH_RE.match(path):
            path = path[1:]
        return path

    if host and host.lower() != "localhost":
        raise tool_error("Only local file:// document URLs are supported.")
    return path


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(path)
    return unique_paths


def _temporary_directory(prefix: str) -> tempfile.TemporaryDirectory[str]:
    temp_root = _document_temp_root()
    if temp_root is not None:
        return tempfile.TemporaryDirectory(prefix=prefix, dir=str(temp_root))
    return tempfile.TemporaryDirectory(prefix=prefix)


def _document_temp_root() -> Path | None:
    candidates = [Path(DOCUMENT_TEMP_ROOT).expanduser()] if DOCUMENT_TEMP_ROOT else [MODULE_DIR / ".tmp" / "documents"]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue
    return None


async def _download_document(url: str) -> DocumentSource:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
    }
    suffix = _suffix_from_url(url) or ".bin"
    tmp_dir = _temporary_directory(prefix="local-mcp-doc-")
    path = Path(tmp_dir.name) / f"document{suffix}"
    total = 0

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT_S, headers=headers) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_DOCUMENT_BYTES:
                    raise tool_error(f"Document is too large. Maximum size is {MAX_DOCUMENT_BYTES} bytes.")
                with path.open("wb") as file:
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_DOCUMENT_BYTES:
                            raise tool_error(f"Document is too large. Maximum size is {MAX_DOCUMENT_BYTES} bytes.")
                        file.write(chunk)
    except Exception as err:
        tmp_dir.cleanup()
        if err.__class__.__name__ == "ToolError":
            raise
        raise tool_error(describe_fetch_error(err, url))

    if path.suffix == ".bin":
        path = _rename_with_detected_suffix(path)
    return DocumentSource(path=path, label=url, cleanup_dir=tmp_dir)


def _decode_data_url(source: str) -> DocumentSource:
    header, separator, payload = source.partition(",")
    if not separator or ";base64" not in header.lower():
        raise tool_error("Only base64 document data URLs are supported.")
    suffix = _suffix_from_mime(header.partition(":")[2].partition(";")[0]) or ".bin"
    return _bytes_document_source(_decode_base64(payload), f"document{suffix}")


def _bytes_document_source(content: bytes, filename: str) -> DocumentSource:
    if len(content) > MAX_DOCUMENT_BYTES:
        raise tool_error(f"Document is too large. Maximum size is {MAX_DOCUMENT_BYTES} bytes.")
    tmp_dir = _temporary_directory(prefix="local-mcp-doc-")
    path = Path(tmp_dir.name) / filename
    path.write_bytes(content)
    if path.suffix == ".bin":
        path = _rename_with_detected_suffix(path)
    return DocumentSource(path=path, label=filename, cleanup_dir=tmp_dir)


def _looks_like_base64(source: str) -> bool:
    compact = "".join(source.split())
    return len(compact) >= 64 and len(compact) % 4 == 0 and bool(BASE64_RE.fullmatch(source))


def _decode_base64(payload: str) -> bytes:
    compact_payload = "".join(payload.split())
    try:
        return base64.b64decode(compact_payload, validate=True)
    except binascii.Error:
        raise tool_error("Document base64 content is invalid.")


def _suffix_from_url(url: str) -> str | None:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix and re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix):
        return suffix
    return None


def _suffix_from_mime(mime: str) -> str | None:
    normalized = (mime or "").lower()
    return {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "text/plain": ".txt",
        "text/markdown": ".md",
        "text/html": ".html",
        "application/json": ".json",
    }.get(normalized)


def _rename_with_detected_suffix(path: Path) -> Path:
    try:
        header = path.read_bytes()[:8]
    except OSError:
        return path
    suffix = ".pdf" if header.startswith(b"%PDF") else ".docx" if header.startswith(b"PK") else ""
    if not suffix:
        return path
    new_path = path.with_suffix(suffix)
    path.replace(new_path)
    return new_path


def _parse_with_pypdf(path: Path, source: str, output_format: str, pages: str) -> ParseResult:
    try:
        from pypdf import PdfReader
    except ImportError as err:
        raise _missing_parser("pypdf") from err

    reader = PdfReader(str(path))
    page_indexes = _parse_page_selection(pages, len(reader.pages))
    selected = page_indexes or list(range(len(reader.pages)))
    page_payloads: list[dict[str, object]] = []

    for index in selected:
        text = reader.pages[index].extract_text() or ""
        page_payloads.append({"page": index + 1, "text": text.strip()})

    metadata = _pypdf_metadata(reader)
    metadata.update({"page_count": len(reader.pages), "selected_pages": [index + 1 for index in selected]})

    if output_format == "json":
        content = json.dumps({"metadata": metadata, "pages": page_payloads}, ensure_ascii=False, indent=2)
    else:
        content = _pages_to_text(page_payloads, include_page_headings=output_format == "markdown")
    return ParseResult("pypdf", output_format, content, source, metadata)


def _parse_with_pdfplumber(path: Path, source: str, output_format: str, pages: str) -> ParseResult:
    try:
        import pdfplumber
    except ImportError as err:
        raise _missing_parser("pdfplumber") from err

    page_payloads: list[dict[str, object]] = []
    with pdfplumber.open(str(path)) as pdf:
        selected = _parse_page_selection(pages, len(pdf.pages)) or list(range(len(pdf.pages)))
        for index in selected:
            page = pdf.pages[index]
            text = (page.extract_text() or "").strip()
            tables = []
            for table in page.find_tables():
                tables.append({"bbox": table.bbox, "rows": table.extract()})
            page_payloads.append({"page": index + 1, "text": text, "tables": tables})
        metadata = {
            "page_count": len(pdf.pages),
            "selected_pages": [index + 1 for index in selected],
            "table_count": sum(len(page["tables"]) for page in page_payloads),
        }

    if output_format == "json":
        content = json.dumps({"metadata": metadata, "pages": page_payloads}, ensure_ascii=False, indent=2)
    else:
        content = _pdfplumber_pages_to_markdown(page_payloads, include_tables=True)
        if output_format == "text":
            content = _strip_markdown_tables(content)
    return ParseResult("pdfplumber", output_format, content, source, metadata)


def _parse_with_pymupdf4llm(path: Path, source: str, output_format: str, pages: str) -> ParseResult:
    try:
        import pymupdf4llm
    except ImportError as err:
        raise _missing_parser("pymupdf4llm") from err

    selected = _parse_page_selection(pages, None)
    if output_format == "json" and hasattr(pymupdf4llm, "to_json"):
        raw = _call_parser_function(pymupdf4llm.to_json, path, selected)
        content = _json_string(raw)
    elif output_format == "text" and hasattr(pymupdf4llm, "to_text"):
        content = str(_call_parser_function(pymupdf4llm.to_text, path, selected)).strip()
    else:
        content = str(_call_parser_function(pymupdf4llm.to_markdown, path, selected)).strip()
    metadata: dict[str, object] = {}
    if selected:
        metadata["selected_pages"] = [index + 1 for index in selected]
    return ParseResult("pymupdf4llm", output_format, content, source, metadata)


def _parse_with_docling(path: Path, source: str, output_format: str, pages: str) -> ParseResult:
    if pages.strip():
        raise tool_error("Docling page selection is not supported by this tool; omit pages or use pypdf/pdfplumber.")
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as err:
        raise _missing_parser("docling") from err

    result = DocumentConverter().convert(str(path))
    document = result.document
    metadata = _object_metadata(result)

    if output_format == "json":
        content = _json_string(_export_object(document, ("export_to_dict", "model_dump", "dict")))
    elif output_format == "text" and hasattr(document, "export_to_text"):
        content = str(document.export_to_text()).strip()
    else:
        content = str(document.export_to_markdown()).strip()
    return ParseResult("docling", output_format, content, source, metadata)


def _parse_with_marker(path: Path, source: str, output_format: str, pages: str) -> ParseResult:
    command = _marker_command()
    if not command:
        raise _missing_parser("marker")

    marker_format = "json" if output_format == "json" else "markdown"
    with _temporary_directory(prefix="local-mcp-marker-") as output_dir:
        args = [
            command,
            str(path),
            "--output_format",
            marker_format,
            "--output_dir",
            output_dir,
            "--disable_image_extraction",
        ]
        marker_pages = _marker_page_range(pages)
        if marker_pages:
            args.extend(["--page_range", marker_pages])
        _run_cli_parser(args, "Marker")
        content_path = _find_parser_output(Path(output_dir), ".json" if marker_format == "json" else ".md")
        content = content_path.read_text(encoding="utf-8", errors="replace").strip()
    metadata = {"cli": command}
    if marker_pages:
        metadata["page_range"] = marker_pages
    return ParseResult("marker", output_format, content, source, metadata)


def _parse_with_mineru(path: Path, source: str, output_format: str, pages: str) -> ParseResult:
    if pages.strip():
        raise tool_error("MinerU page selection is not supported by this tool; omit pages or use pypdf/pdfplumber.")
    command = _mineru_command()
    if not command:
        raise _missing_parser("mineru")

    backend = os.environ.get("LOCAL_MCP_MINERU_BACKEND", "pipeline").strip()
    with _temporary_directory(prefix="local-mcp-mineru-") as output_dir:
        args = [command, "-p", str(path), "-o", output_dir]
        if backend:
            args.extend(["-b", backend])
        _run_cli_parser(args, "MinerU")
        suffix = ".json" if output_format == "json" else ".md"
        content_path = _find_parser_output(Path(output_dir), suffix)
        content = content_path.read_text(encoding="utf-8", errors="replace").strip()
    metadata = {"cli": command}
    if backend:
        metadata["backend"] = backend
    return ParseResult("mineru", output_format, content, source, metadata)


def _parse_plain_text(path: Path, source: str, output_format: str, pages: str) -> ParseResult:
    if pages.strip():
        raise tool_error("Page selection is only supported for PDF parsers.")
    try:
        content = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as err:
        raise tool_error(f"Could not read text document: {err}")
    if output_format == "json":
        content = json.dumps({"text": content}, ensure_ascii=False, indent=2)
    return ParseResult("text", output_format, content, source, {"bytes": path.stat().st_size})


def _pypdf_metadata(reader) -> dict[str, object]:
    metadata: dict[str, object] = {}
    raw_metadata = getattr(reader, "metadata", None)
    if raw_metadata:
        for key, value in dict(raw_metadata).items():
            metadata[str(key).lstrip("/")] = str(value)
    return metadata


def _object_metadata(value: object) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for name in ("status", "input", "timings"):
        if hasattr(value, name):
            attr = getattr(value, name)
            metadata[name] = str(attr)
    return metadata


def _export_object(value: object, methods: tuple[str, ...]) -> object:
    for method_name in methods:
        method = getattr(value, method_name, None)
        if callable(method):
            return method()
    return str(value)


def _call_parser_function(func, path: Path, pages: list[int] | None) -> object:
    kwargs = {}
    if pages:
        try:
            signature = inspect.signature(func)
            accepts_pages = "pages" in signature.parameters
        except (TypeError, ValueError):
            accepts_pages = True
        if not accepts_pages:
            raise tool_error(f"{func.__module__}.{func.__name__} does not support page selection.")
        kwargs["pages"] = pages
    return func(str(path), **kwargs)


def _parse_page_selection(pages: str, page_count: int | None) -> list[int] | None:
    value = (pages or "").strip()
    if not value:
        return None

    selected: list[int] = []
    seen: set[int] = set()
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            if not start_text.strip().isdigit() or not end_text.strip().isdigit():
                raise tool_error("Pages must look like `1-3,5`.")
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise tool_error("Page ranges must be ascending.")
            numbers = range(start, end + 1)
        else:
            if not token.isdigit():
                raise tool_error("Pages must look like `1-3,5`.")
            numbers = range(int(token), int(token) + 1)

        for number in numbers:
            if number < 1:
                raise tool_error("Pages are 1-based; page numbers must be at least 1.")
            index = number - 1
            if page_count is not None and index >= page_count:
                raise tool_error(f"Page {number} is outside the document's {page_count} pages.")
            if index not in seen:
                seen.add(index)
                selected.append(index)
    return selected


def _marker_page_range(pages: str) -> str:
    selected = _parse_page_selection(pages, None)
    if not selected:
        return ""
    ranges: list[str] = []
    start = selected[0]
    previous = selected[0]
    for index in selected[1:]:
        if index == previous + 1:
            previous = index
            continue
        ranges.append(f"{start}" if start == previous else f"{start}-{previous}")
        start = previous = index
    ranges.append(f"{start}" if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def _pages_to_text(page_payloads: list[dict[str, object]], *, include_page_headings: bool) -> str:
    chunks: list[str] = []
    for page in page_payloads:
        text = str(page.get("text") or "").strip()
        if include_page_headings:
            chunks.append(f"## Page {page['page']}\n\n{text}".strip())
        elif text:
            chunks.append(text)
    return "\n\n".join(chunks).strip()


def _pdfplumber_pages_to_markdown(page_payloads: list[dict[str, object]], *, include_tables: bool) -> str:
    chunks: list[str] = []
    for page in page_payloads:
        page_chunks = [f"## Page {page['page']}"]
        text = str(page.get("text") or "").strip()
        if text:
            page_chunks.append(text)
        if include_tables:
            for index, table in enumerate(page.get("tables") or [], start=1):
                rows = table.get("rows") if isinstance(table, dict) else None
                bbox = table.get("bbox") if isinstance(table, dict) else None
                page_chunks.append(f"### Table {index}")
                if bbox:
                    page_chunks.append(f"Coordinates: {bbox}")
                page_chunks.append(_rows_to_markdown(rows or []))
        chunks.append("\n\n".join(page_chunks).strip())
    return "\n\n".join(chunks).strip()


def _rows_to_markdown(rows: list[list[object]]) -> str:
    normalized = [[_cell_text(cell) for cell in row] for row in rows if row]
    if not normalized:
        return ""
    width = max(len(row) for row in normalized)
    padded = [row + [""] * (width - len(row)) for row in normalized]
    header = padded[0]
    separator = ["---"] * width
    body = padded[1:]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(separator) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _cell_text(value: object) -> str:
    return str(value if value is not None else "").replace("\n", " ").strip()


def _strip_markdown_tables(markdown: str) -> str:
    lines = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") or stripped.startswith("Coordinates:") or stripped.startswith("### Table"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _json_string(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _format_result(result: ParseResult, *, include_metadata: bool, max_chars: int) -> str:
    content, truncated = _truncate(result.content, max_chars)
    warnings = list(result.warnings)
    if truncated:
        warnings.append(f"Content truncated to {max_chars} characters.")

    if result.output_format == "json":
        payload = {
            "parser": result.parser,
            "source": result.source,
            "output_format": result.output_format,
            "metadata": result.metadata,
            "warnings": warnings,
            "content": content,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    if not include_metadata:
        return content

    lines = [
        f"Parser: {result.parser}",
        f"Source: {result.source}",
        f"Output format: {result.output_format}",
    ]
    if result.metadata:
        lines.append("Metadata:")
        for key, value in result.metadata.items():
            lines.append(f"- {key}: {value}")
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines).strip() + "\n\n" + content


def _truncate(content: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(content) <= max_chars:
        return content, False
    return content[:max_chars].rstrip(), True


def _validate_choice(value: str, allowed: set[str], label: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in allowed:
        choices = ", ".join(sorted(allowed))
        raise tool_error(f"Unsupported {label}: {value}. Choose one of: {choices}.")
    return normalized


def _missing_parser(parser: str):
    return tool_error(f"{parser} is not installed or not on PATH. {INSTALL_HINTS.get(parser, '')}".strip())


def _marker_command() -> str | None:
    return os.environ.get("LOCAL_MCP_MARKER_CMD") or shutil.which("marker_single")


def _mineru_command() -> str | None:
    return os.environ.get("LOCAL_MCP_MINERU_CMD") or shutil.which("mineru")


def _run_cli_parser(args: list[str], label: str) -> None:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            check=False,
            text=True,
            timeout=PARSER_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as err:
        raise tool_error(f"{label} timed out after {PARSER_TIMEOUT_S} seconds.") from err
    except OSError as err:
        raise tool_error(f"Could not start {label}: {err}") from err

    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        if len(stderr) > 1200:
            stderr = stderr[:1200].rstrip()
        raise tool_error(f"{label} failed with exit code {completed.returncode}: {stderr}")


def _find_parser_output(output_dir: Path, suffix: str) -> Path:
    matches = [path for path in output_dir.rglob(f"*{suffix}") if path.is_file()]
    if not matches:
        raise tool_error(f"Parser completed but no {suffix} output file was found.")
    return max(matches, key=lambda path: path.stat().st_size)
