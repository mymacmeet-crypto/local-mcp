"""Document source loading from paths, URLs, data URLs, and base64."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from urllib.parse import ParseResult as UrlParseResult
from urllib.parse import urlparse

import httpx

from local_mcp.documents.models import DocumentSource
from local_mcp.shared.errors import describe_fetch_error, tool_error
from local_mcp.shared.files import clean_wrapped_source, decode_base64, local_path_candidates, looks_like_base64
from local_mcp.web.fetcher import TIMEOUT_S, USER_AGENT

MAX_DOCUMENT_BYTES = int(os.environ.get("LOCAL_MCP_DOCUMENT_MAX_BYTES", str(100 * 1024 * 1024)))
DOCUMENT_TEMP_ROOT = os.environ.get("LOCAL_MCP_DOCUMENT_TMPDIR", "")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


async def load_document_source(document: str) -> DocumentSource:
    source = clean_wrapped_source(document)
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

    if looks_like_base64(source, min_length=64):
        return _bytes_document_source(_decode_document_base64(source), "document.pdf")

    raise tool_error(f"Document not found or unsupported document source: {source}")


def _local_document_source(source: str, parsed: UrlParseResult) -> DocumentSource | None:
    for path in local_path_candidates(source, parsed, relative_root=PROJECT_ROOT, source_kind="document"):
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


def temporary_directory(prefix: str) -> tempfile.TemporaryDirectory[str]:
    temp_root = _document_temp_root()
    if temp_root is not None:
        return tempfile.TemporaryDirectory(prefix=prefix, dir=str(temp_root))
    return tempfile.TemporaryDirectory(prefix=prefix)


def _document_temp_root() -> Path | None:
    candidates = [Path(DOCUMENT_TEMP_ROOT).expanduser()] if DOCUMENT_TEMP_ROOT else [PROJECT_ROOT / ".tmp" / "documents"]
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
    tmp_dir = temporary_directory(prefix="local-mcp-doc-")
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
    return _bytes_document_source(_decode_document_base64(payload), f"document{suffix}")


def _bytes_document_source(content: bytes, filename: str) -> DocumentSource:
    if len(content) > MAX_DOCUMENT_BYTES:
        raise tool_error(f"Document is too large. Maximum size is {MAX_DOCUMENT_BYTES} bytes.")
    tmp_dir = temporary_directory(prefix="local-mcp-doc-")
    path = Path(tmp_dir.name) / filename
    path.write_bytes(content)
    if path.suffix == ".bin":
        path = _rename_with_detected_suffix(path)
    return DocumentSource(path=path, label=filename, cleanup_dir=tmp_dir)


def _decode_document_base64(payload: str) -> bytes:
    return decode_base64(payload, source_kind="document")


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
