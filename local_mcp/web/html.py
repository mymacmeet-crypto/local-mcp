"""HTML URL extraction and content scraping helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable
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


def extract_link_details(
    html: str,
    base_url: str,
    *,
    selector: str | None = None,
    same_domain: bool = False,
    limit: int = 100,
) -> list[dict[str, str]]:
    """Return unique link URLs with visible labels from the whole page or a CSS selector."""
    soup = BeautifulSoup(html or "", "lxml")
    container = _select_container(soup, selector) if (selector or "").strip() else soup
    if container is None:
        return []
    base_host = urlparse(base_url).hostname or ""
    links: list[dict[str, str]] = []
    seen: set[str] = set()

    for tag in container.select("a[href], link[href], area[href]"):
        url = normalize_discovered_url(tag.get("href") or "", base_url)
        if not url or url in seen:
            continue
        if same_domain and (urlparse(url).hostname or "") != base_host:
            continue
        seen.add(url)
        links.append(
            {
                "url": url,
                "text": tag.get_text(" ", strip=True) or tag.get("title", "").strip(),
            }
        )
        if len(links) >= limit:
            break

    return links


def extract_images(
    html: str,
    base_url: str,
    *,
    selector: str | None = None,
    limit: int = 100,
) -> list[dict[str, str]]:
    """Return unique image URLs with common descriptive attributes."""
    soup = BeautifulSoup(html or "", "lxml")
    container = _select_container(soup, selector) if (selector or "").strip() else soup
    if container is None:
        return []
    images: list[dict[str, str]] = []
    seen: set[str] = set()

    for tag in container.select("img[src]"):
        src = _normalize_media_url(tag.get("src") or "", base_url)
        if not src or src in seen:
            continue
        seen.add(src)
        image = {
            "url": src,
            "alt": tag.get("alt", "").strip(),
            "title": tag.get("title", "").strip(),
        }
        width = tag.get("width", "").strip()
        height = tag.get("height", "").strip()
        if width:
            image["width"] = width
        if height:
            image["height"] = height
        images.append(image)
        if len(images) >= limit:
            break

    return images


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


def extract_metadata(html: str, base_url: str | None = None) -> dict[str, str]:
    """Extract common page metadata for fetch/scrape responses."""
    soup = BeautifulSoup(html or "", "lxml")
    metadata: dict[str, str] = {}

    title = soup.title.get_text(strip=True) if soup.title and soup.title.get_text(strip=True) else None
    if not title:
        title = extract_title(html)
    if title:
        metadata["title"] = title

    description = _first_meta_content(
        soup,
        ('meta[name="description"]', "content"),
        ('meta[property="og:description"]', "content"),
        ('meta[name="twitter:description"]', "content"),
    )
    if description:
        metadata["description"] = description

    canonical = _first_attr(soup, ('link[rel~="canonical"][href]', "href"))
    if canonical:
        resolved_canonical = normalize_discovered_url(canonical, base_url) if base_url else canonical
        if resolved_canonical:
            metadata["canonical_url"] = resolved_canonical

    lang = _first_attr(soup, ("html[lang]", "lang"))
    if lang:
        metadata["language"] = lang

    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        metadata["h1"] = h1.get_text(" ", strip=True)

    return metadata


def html_fragment(html: str, selector: str | None = None) -> str:
    """Return the full HTML document or a joined CSS-selected fragment."""
    selector = (selector or "").strip()
    if not selector:
        return html or ""
    soup = BeautifulSoup(html or "", "lxml")
    nodes = soup.select(selector)
    return "\n".join(str(node) for node in nodes).strip()


def html_to_text(html: str, *, selector: str | None = None) -> str:
    """Extract readable plain text from the whole page or a CSS selector."""
    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup(list(_NOISE_TAGS)):
        tag.decompose()
    container = _select_container(soup, selector)
    if container is None:
        return ""
    return _collapse_blank_lines(container.get_text("\n", strip=True)).strip()


def html_to_markdown(html: str, base_url: str | None = None, *, selector: str | None = None) -> str:
    """Convert an HTML document to Markdown, dropping non-content noise.

    Strips scripts, styles, and other non-readable tags, prefers the main
    content region when one is marked up, optionally narrows extraction to a
    CSS selector, resolves relative links/images against ``base_url``, and
    returns trimmed Markdown text.
    """
    from markdownify import markdownify as _markdownify

    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup(list(_NOISE_TAGS)):
        tag.decompose()

    container = _select_container(soup, selector)
    if container is None:
        return ""
    if base_url:
        _absolutize_refs(container, base_url)

    markdown = _markdownify(str(container), heading_style="ATX")
    return _collapse_blank_lines(markdown).strip()


def _select_container(soup: BeautifulSoup, selector: str | None = None):
    selector = (selector or "").strip()
    if selector:
        nodes = soup.select(selector)
        if not nodes:
            return None
        fragment = BeautifulSoup("\n".join(str(node) for node in nodes), "lxml")
        return fragment.body or fragment
    return soup.find("main") or soup.find("article") or soup.body or soup


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


def _normalize_media_url(raw_url: str, base_url: str) -> str | None:
    try:
        absolute_url = urljoin(base_url, raw_url.strip())
    except ValueError:
        return None
    parsed = urlparse(absolute_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return absolute_url


def _first_meta_content(soup: BeautifulSoup, *selectors: tuple[str, str]) -> str | None:
    return _first_attr(soup, *selectors)


def _first_attr(soup: BeautifulSoup, *selectors: tuple[str, str]) -> str | None:
    for selector, attr in selectors:
        tag = soup.select_one(selector)
        if not tag:
            continue
        value = tag.get(attr)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if _is_string_iterable(value):
            joined = " ".join(str(item).strip() for item in value if str(item).strip())
            if joined:
                return joined
    return None


def _is_string_iterable(value: object) -> bool:
    return isinstance(value, Iterable) and not isinstance(value, (str, bytes))


def _collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text or "")
