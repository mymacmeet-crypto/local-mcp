"""Fetch pages with httpx first, then crawl4ai when browser rendering is needed."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx

USER_AGENT = os.environ.get(
    "CLAW_SITE_USER_AGENT",
    "claw-site/1.0 (+https://github.com/your-org/claw-site)",
)
TIMEOUT_MS = int(os.environ.get("CLAW_SITE_TIMEOUT_MS", "15000"))
TIMEOUT_S = TIMEOUT_MS / 1000.0


@dataclass
class FetchResult:
    html: str
    final_url: str
    status: int


async def fetch_static(url: str, *, accept: str | None = None) -> FetchResult:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept or "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT_S, headers=headers) as client:
        response = await client.get(url)

    if response.status_code >= 500:
        response.raise_for_status()

    return FetchResult(html=response.text, final_url=str(response.url), status=response.status_code)


_crawler: Optional[Any] = None
_crawler_lock = asyncio.Lock()


async def get_crawler():
    global _crawler
    if _crawler is not None:
        return _crawler
    async with _crawler_lock:
        if _crawler is not None:
            return _crawler
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig
        except ImportError as err:
            raise RuntimeError(
                "Browser rendering is unavailable: the optional 'crawl4ai' dependency "
                "is not installed. Install it with `pip install \"claw-site[browser]\"`."
            ) from err

        browser_config = BrowserConfig(headless=True, user_agent=USER_AGENT, verbose=False)
        crawler = AsyncWebCrawler(config=browser_config)
        await crawler.start()
        _crawler = crawler
        return _crawler


async def close_crawler() -> None:
    global _crawler
    if _crawler is not None:
        try:
            await _crawler.close()
        finally:
            _crawler = None


def _run_config():
    from crawl4ai import CacheMode, CrawlerRunConfig

    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=TIMEOUT_MS,
        wait_until="networkidle",
        verbose=False,
    )


async def fetch_browser(url: str) -> FetchResult:
    crawler = await get_crawler()
    result = await crawler.arun(url=url, config=_run_config())
    if not getattr(result, "success", True):
        raise RuntimeError(getattr(result, "error_message", None) or f"crawl4ai failed for {url}")
    return FetchResult(
        html=result.html or "",
        final_url=getattr(result, "url", None) or url,
        status=getattr(result, "status_code", None) or 200,
    )
