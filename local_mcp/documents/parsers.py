"""Document parser backend selection and implementations."""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import shutil
import subprocess
from pathlib import Path

from local_mcp.documents.formatting import json_string
from local_mcp.documents.models import ParseResult
from local_mcp.documents.source import temporary_directory
from local_mcp.shared.errors import tool_error

PARSER_TIMEOUT_S = int(os.environ.get("LOCAL_MCP_DOCUMENT_PARSER_TIMEOUT_S", "900"))

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


def parse_document_path(path: Path, source_label: str, parser: str, output_format: str, pages: str) -> ParseResult:
    selected_parser = choose_auto_parser(path) if parser == "auto" else parser
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


def choose_auto_parser(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        for parser in ("pymupdf4llm", "pypdf", "pdfplumber", "docling"):
            if parser_available(parser):
                return parser
    if suffix in TEXT_EXTENSIONS:
        return "text"
    for parser in ("docling", "marker", "mineru", "pymupdf4llm"):
        if parser_available(parser):
            return parser
    raise tool_error(
        "No document parser is available for this file. "
        "Install `pypdf` for PDFs or optional document parsers from pyproject extras."
    )


def parser_available(parser: str) -> bool:
    if parser == "marker":
        return bool(_marker_command())
    if parser == "mineru":
        return bool(_mineru_command())
    if parser == "text":
        return True
    return _has_module(parser)


def _has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _parse_with_pypdf(path: Path, source: str, output_format: str, pages: str) -> ParseResult:
    try:
        from pypdf import PdfReader
    except ImportError as err:
        raise _missing_parser("pypdf") from err

    reader = PdfReader(str(path))
    page_indexes = parse_page_selection(pages, len(reader.pages))
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
        selected = parse_page_selection(pages, len(pdf.pages)) or list(range(len(pdf.pages)))
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

    selected = parse_page_selection(pages, None)
    if output_format == "json" and hasattr(pymupdf4llm, "to_json"):
        raw = _call_parser_function(pymupdf4llm.to_json, path, selected)
        content = json_string(raw)
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
        content = json_string(_export_object(document, ("export_to_dict", "model_dump", "dict")))
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
    with temporary_directory(prefix="local-mcp-marker-") as output_dir:
        args = [
            command,
            str(path),
            "--output_format",
            marker_format,
            "--output_dir",
            output_dir,
            "--disable_image_extraction",
        ]
        marker_pages = marker_page_range(pages)
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
    with temporary_directory(prefix="local-mcp-mineru-") as output_dir:
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


def parse_page_selection(pages: str, page_count: int | None) -> list[int] | None:
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


def marker_page_range(pages: str) -> str:
    selected = parse_page_selection(pages, None)
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
