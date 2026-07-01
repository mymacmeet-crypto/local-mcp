"""Shared local-file, file URI, and base64 helpers."""

from __future__ import annotations

import base64
import binascii
import os
import re
from pathlib import Path
from urllib.parse import ParseResult, unquote

from local_mcp.shared.errors import tool_error

BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")
WINDOWS_DRIVE_PATH_RE = re.compile(r"^/[A-Za-z]:([\\/]|$)")


def clean_wrapped_source(value: str) -> str:
    source = (value or "").strip()
    if len(source) >= 2 and source[0] == source[-1] and source[0] in ("'", '"'):
        return source[1:-1].strip()
    return source


def file_uri_to_path(parsed: ParseResult, *, source_kind: str) -> str:
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
        raise tool_error(f"Only local file:// {source_kind} URLs are supported.")
    return path


def local_path_candidates(source: str, parsed: ParseResult, *, relative_root: Path, source_kind: str) -> list[Path]:
    if parsed.scheme == "file":
        path_source = file_uri_to_path(parsed, source_kind=source_kind)
    else:
        path_source = source

    path = Path(path_source).expanduser()
    candidates = [path]
    if not path.is_absolute():
        candidates.append(Path.cwd() / path)
        candidates.append(relative_root / path)
    return unique_paths(candidates)


def unique_paths(paths: list[Path]) -> list[Path]:
    unique_values: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique_values.append(path)
    return unique_values


def looks_like_base64(source: str, *, min_length: int) -> bool:
    compact = "".join(source.split())
    return len(compact) >= min_length and len(compact) % 4 == 0 and bool(BASE64_RE.fullmatch(source))


def decode_base64(payload: str, *, source_kind: str) -> bytes:
    compact_payload = "".join(payload.split())
    try:
        return base64.b64decode(compact_payload, validate=True)
    except binascii.Error:
        raise tool_error(f"{source_kind.capitalize()} base64 content is invalid.")
