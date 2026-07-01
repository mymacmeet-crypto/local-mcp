"""robots.txt sitemap discovery and XML sitemap parsing."""

from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

from local_mcp.shared.urls import normalize_discovered_url
from local_mcp.web import fetcher

SITEMAP_RE = re.compile(r"^\s*sitemap\s*:\s*(?P<url>\S+)\s*$", re.I | re.M)
SourcedUrl = tuple[str, str]


def site_root(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"


async def discover_sitemaps(url: str) -> list[SourcedUrl]:
    root = site_root(url)
    candidates: list[SourcedUrl] = []

    robots_url = urljoin(root, "robots.txt")
    try:
        robots = await fetcher.fetch_static(robots_url, accept="text/plain,*/*;q=0.8")
        for match in SITEMAP_RE.finditer(robots.html):
            sitemap_url = normalize_discovered_url(match.group("url"), root)
            if sitemap_url:
                candidates.append((sitemap_url, "robots.txt"))
    except Exception:
        pass

    candidates.append((urljoin(root, "sitemap.xml"), "sitemap.xml"))
    return _unique_sourced(candidates)


async def collect_sitemap_urls(
    start_url: str,
    *,
    limit: int,
    url_filter: Callable[[str], bool] | None = None,
) -> list[SourcedUrl]:
    pending = await discover_sitemaps(start_url)
    seen_sitemaps: set[str] = set()
    urls: list[SourcedUrl] = []
    seen_urls: set[str] = set()

    while pending and len(urls) < limit:
        sitemap_url, sitemap_source = pending.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        try:
            page = await fetcher.fetch_static(sitemap_url, accept="application/xml,text/xml,*/*;q=0.8")
        except Exception:
            continue

        child_sitemaps, page_urls = parse_sitemap(page.html, page.final_url)
        pending.extend((url, sitemap_source) for url in child_sitemaps if url not in seen_sitemaps)
        for page_url in page_urls:
            if url_filter and not url_filter(page_url):
                continue
            if page_url in seen_urls:
                continue
            seen_urls.add(page_url)
            urls.append((page_url, sitemap_source))
            if len(urls) >= limit:
                break

    return urls


def parse_sitemap(xml_text: str, base_url: str) -> tuple[list[str], list[str]]:
    if not xml_text.strip():
        return [], []
    xml_text = _maybe_decompress_text(xml_text)

    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return [], []

    sitemaps: list[str] = []
    urls: list[str] = []
    for loc in root.iter():
        if _strip_namespace(loc.tag) != "loc" or not loc.text:
            continue
        parsed_url = normalize_discovered_url(loc.text, base_url)
        if not parsed_url:
            continue
        if parsed_url.endswith((".xml", ".xml.gz")):
            sitemaps.append(parsed_url)
        else:
            urls.append(parsed_url)

    return _unique(sitemaps), _unique(urls)


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _maybe_decompress_text(text: str) -> str:
    if not text:
        return text
    raw = text.encode("latin1", errors="ignore")
    if not raw.startswith(b"\x1f\x8b"):
        return text
    try:
        return gzip.decompress(raw).decode("utf-8", errors="replace")
    except OSError:
        return text


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values


def _unique_sourced(values: list[SourcedUrl]) -> list[SourcedUrl]:
    seen: set[str] = set()
    unique_values: list[SourcedUrl] = []
    for value, source in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append((value, source))
    return unique_values
