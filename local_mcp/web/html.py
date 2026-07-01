"""HTML URL extraction helpers."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from local_mcp.shared.urls import normalize_discovered_url


def extract_links(html: str, base_url: str, *, same_domain: bool = True) -> list[str]:
    soup = BeautifulSoup(html or "", "lxml")
    base_host = urlparse(base_url).hostname or ""
    urls: list[str] = []
    seen: set[str] = set()

    for tag in soup.select("a[href], link[href], area[href]"):
        url = normalize_discovered_url(tag.get("href") or "", base_url)
        if not url:
            continue
        if same_domain and (urlparse(url).hostname or "") != base_host:
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)

    return urls


def has_extractable_content(html: str, base_url: str, *, same_domain: bool = True) -> bool:
    return bool(extract_links(html, base_url, same_domain=same_domain))


# Tags that carry no readable content and only add noise to the markdown.
_NOISE_TAGS = ("script", "style", "noscript", "template", "svg", "iframe", "form")


def extract_title(html: str) -> str | None:
    soup = BeautifulSoup(html or "", "lxml")
    heading = soup.find("h1")
    if heading and heading.get_text(strip=True):
        return heading.get_text(strip=True)
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(strip=True)
    return None


def html_to_markdown(html: str, base_url: str | None = None) -> str:
    """Convert an HTML document to Markdown, dropping non-content noise.

    Strips scripts, styles, and other non-readable tags, prefers the main
    content region when one is marked up, resolves relative links/images
    against ``base_url``, and returns trimmed Markdown text.
    """
    from markdownify import markdownify as _markdownify

    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup(list(_NOISE_TAGS)):
        tag.decompose()

    container = soup.find("main") or soup.find("article") or soup.body or soup
    if base_url:
        _absolutize_refs(container, base_url)

    markdown = _markdownify(str(container), heading_style="ATX")
    return _collapse_blank_lines(markdown).strip()


def _absolutize_refs(node, base_url: str) -> None:
    for tag in node.select("a[href]"):
        resolved = normalize_discovered_url(tag.get("href") or "", base_url)
        if resolved:
            tag["href"] = resolved
    for tag in node.select("img[src]"):
        try:
            tag["src"] = urljoin(base_url, (tag.get("src") or "").strip())
        except ValueError:
            pass


def _collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text or "")
