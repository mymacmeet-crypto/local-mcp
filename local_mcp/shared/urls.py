"""URL normalization and formatting helpers."""

from __future__ import annotations

import re
from urllib.parse import quote, urljoin, urlparse, urlunparse

from local_mcp.shared.errors import tool_error


def normalize_url(raw: str) -> str:
    candidate = (raw or "").strip()
    if not candidate:
        raise tool_error('"" is not a valid URL.')
    if re.match(r"^https?//", candidate, re.I):
        candidate = candidate.replace("//", "://", 1)

    parsed = urlparse(candidate)
    if not parsed.scheme:
        parsed = urlparse(f"https://{candidate}")

    if parsed.scheme not in ("http", "https"):
        raise tool_error(f"Only http and https URLs are supported (got {parsed.scheme or '<none>'}).")
    if not parsed.netloc:
        raise tool_error(f'"{raw}" is not a valid URL.')

    return urlunparse(parsed)


def normalize_discovered_url(raw_url: str, base_url: str | None = None) -> str | None:
    raw = (raw_url or "").strip()
    if not raw or re.match(r"^(javascript:|mailto:|tel:|#)", raw, re.I):
        return None
    try:
        absolute_url = urljoin(base_url, raw) if base_url else raw
    except ValueError:
        return None
    parsed = urlparse(absolute_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return urlunparse(parsed._replace(fragment=""))


def same_hostname(left_url: str, right_url: str) -> bool:
    return (urlparse(left_url).hostname or "") == (urlparse(right_url).hostname or "")


def same_path_prefix(left_url: str, right_url: str) -> bool:
    if not same_hostname(left_url, right_url):
        return False

    left_path = url_route_path(left_url)
    right_path = url_route_path(right_url)
    if right_path == "/":
        return True
    return left_path == right_path or left_path.startswith(f"{right_path}/")


def url_route_path(url: str) -> str:
    return normalize_route_path(urlparse(url).path)


def normalize_route_path(path: str) -> str:
    return f"/{(path or '').strip('/')}"


def markdown_link_target(url: str) -> str:
    return quote(url, safe=":/?#[]@!$&'()*+,;=%")
