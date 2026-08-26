"""Aion Hand Browser Module — web automation with graceful fallback.

Provides:
    - Browser.fetch(url) — fetch HTML, parse, extract text/links
    - Browser.scrape(url, selector) — extract specific elements
    - Browser.screenshot(url) — render page to PNG (requires Playwright)
    - Browser.click(url, selector) — interactive automation (requires Playwright)
    - Browser.fill_form(url, fields) — fill and submit forms

Backends:
    1. Playwright (if `playwright` package installed and browsers installed)
    2. urllib + html.parser (stdlib fallback — fetches HTML, no JS execution)

Usage:
    from aion_core.browser import Browser
    b = Browser()
    html = await b.fetch("https://example.com")
    text = await b.fetch_text("https://example.com")
    links = await b.fetch_links("https://example.com")
"""

from __future__ import annotations

import asyncio
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

logger = __import__("logging").getLogger("aion_hand.browser")


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------

def _playwright_available() -> bool:
    try:
        import playwright  # type: ignore[import-not-found]  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Stdlib HTML parser
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Extract visible text from HTML, ignoring scripts/styles."""
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = False
        self._skip_tags = {"script", "style", "noscript", "head"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags:
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self._chunks.append(text)

    def get_text(self) -> str:
        return " ".join(self._chunks)


class _LinkExtractor(HTMLParser):
    """Extract all <a href> links from HTML."""
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []  # (href, text)
        self._in_a = False
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._in_a = True
            for k, v in attrs:
                if k == "href" and v:
                    self._current_href = v

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_a:
            text = " ".join(self._current_text).strip()
            if self._current_href:
                self.links.append((self._current_href, text))
            self._in_a = False
            self._current_href = None
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._in_a:
            t = data.strip()
            if t:
                self._current_text.append(t)


class _TitleExtractor(HTMLParser):
    """Extract the <title> of an HTML document."""
    def __init__(self) -> None:
        super().__init__()
        self.title: str = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


class _MetaExtractor(HTMLParser):
    """Extract <meta name="description"> and other meta tags."""
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            d = dict(attrs)
            name = d.get("name") or d.get("property") or d.get("charset")
            content = d.get("content")
            if name and content:
                self.meta[name] = content


# ---------------------------------------------------------------------------
# Parsed page
# ---------------------------------------------------------------------------

@dataclass
class Page:
    """A fetched web page."""
    url: str
    status: int
    html: str
    text: str = ""
    title: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)
    final_url: str = ""  # after redirects

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "final_url": self.final_url or self.url,
            "status": self.status,
            "title": self.title,
            "text_length": len(self.text),
            "links_count": len(self.links),
            "meta": self.meta,
            "text_preview": self.text[:500],
        }


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------

class Browser:
    """Multi-backend web browser automation."""

    USER_AGENT = "Mozilla/5.0 (compatible; AionHand/0.3; +https://github.com/xdadik/Aion)"

    def __init__(self, *, use_playwright: bool = True, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self._use_pw = use_playwright and _playwright_available()
        self._pw_browser: Any = None
        logger.info(f"Browser init: playwright={self._use_pw}")

    @property
    def backend(self) -> str:
        return "playwright" if self._use_pw else "urllib"

    # ------------------------------------------------------------------
    #  Fetch
    # ------------------------------------------------------------------

    async def fetch(self, url: str, *, follow_redirects: bool = True) -> Page:
        """Fetch a URL and return a parsed Page."""
        if self._use_pw:
            return await self._fetch_playwright(url)
        return await self._fetch_urllib(url, follow_redirects=follow_redirects)

    async def fetch_text(self, url: str) -> str:
        """Convenience: return only the visible text of a page."""
        page = await self.fetch(url)
        return page.text

    async def fetch_links(self, url: str) -> list[tuple[str, str]]:
        """Convenience: return only the links of a page."""
        page = await self.fetch(url)
        return page.links

    async def fetch_html(self, url: str) -> str:
        """Convenience: return only the raw HTML."""
        page = await self.fetch(url)
        return page.html

    async def _fetch_urllib(self, url: str, *, follow_redirects: bool = True) -> Page:
        """Stdlib-based fetch — no JS execution."""
        def _do_fetch() -> tuple[int, str, str]:
            req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                final_url = resp.geturl()
                status = resp.status
                # Read up to 5 MB
                raw = resp.read(5 * 1024 * 1024)
                charset = resp.headers.get_content_charset() or "utf-8"
                html = raw.decode(charset, errors="replace")
                return status, html, final_url

        status, html, final_url = await asyncio.get_event_loop().run_in_executor(None, _do_fetch)

        # Parse
        text_extractor = _TextExtractor()
        text_extractor.feed(html)
        text = text_extractor.get_text()

        title_extractor = _TitleExtractor()
        title_extractor.feed(html)

        link_extractor = _LinkExtractor()
        link_extractor.feed(html)

        meta_extractor = _MetaExtractor()
        meta_extractor.feed(html)

        # Resolve relative links
        base = final_url or url
        resolved_links: list[tuple[str, str]] = []
        for href, link_text in link_extractor.links:
            absolute = urllib.parse.urljoin(base, href)
            resolved_links.append((absolute, link_text))

        return Page(
            url=url,
            status=status,
            html=html,
            text=text,
            title=title_extractor.title.strip(),
            links=resolved_links,
            meta=meta_extractor.meta,
            final_url=final_url,
        )

    async def _fetch_playwright(self, url: str) -> Page:
        """Playwright-based fetch — full JS execution."""
        if self._pw_browser is None:
            from playwright.async_api import async_playwright  # type: ignore[import-not-found]
            self._pw = await async_playwright().start()
            self._pw_browser = await self._pw.chromium.launch(headless=True)

        page = await self._pw_browser.new_page()
        try:
            response = await page.goto(url, timeout=int(self.timeout * 1000), wait_until="domcontentloaded")
            status = response.status if response else 0
            html = await page.content()
            title = await page.title()
            text = await page.evaluate("() => document.body.innerText")
            links_raw = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                    href: a.href,
                    text: a.innerText.trim()
                }));
            }""")
            links = [(l["href"], l["text"]) for l in links_raw if l.get("href")]
            meta_raw = await page.evaluate("""() => {
                const meta = {};
                document.querySelectorAll('meta[name], meta[property]').forEach(m => {
                    const key = m.getAttribute('name') || m.getAttribute('property');
                    const val = m.getAttribute('content');
                    if (key && val) meta[key] = val;
                });
                return meta;
            }""")
            final_url = page.url
        finally:
            await page.close()

        return Page(
            url=url,
            status=status,
            html=html,
            text=text,
            title=title,
            links=links,
            meta=meta_raw,
            final_url=final_url,
        )

    # ------------------------------------------------------------------
    #  Advanced (Playwright only)
    # ------------------------------------------------------------------

    async def screenshot(self, url: str, output_path: Path | str, *, full_page: bool = True) -> Path:
        """Render a URL and save a screenshot. Requires Playwright."""
        if not self._use_pw:
            raise RuntimeError("screenshot() requires Playwright. Install: pip install playwright && playwright install chromium")
        if self._pw_browser is None:
            from playwright.async_api import async_playwright  # type: ignore[import-not-found]
            self._pw = await async_playwright().start()
            self._pw_browser = await self._pw.chromium.launch(headless=True)

        page = await self._pw_browser.new_page()
        try:
            await page.goto(url, timeout=int(self.timeout * 1000), wait_until="networkidle")
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(out), full_page=full_page)
            return out
        finally:
            await page.close()

    async def click(self, url: str, selector: str, *, wait: float = 2.0) -> Page:
        """Navigate to URL, click an element, return the resulting page."""
        if not self._use_pw:
            raise RuntimeError("click() requires Playwright")
        if self._pw_browser is None:
            from playwright.async_api import async_playwright  # type: ignore[import-not-found]
            self._pw = await async_playwright().start()
            self._pw_browser = await self._pw.chromium.launch(headless=True)

        page = await self._pw_browser.new_page()
        try:
            await page.goto(url, timeout=int(self.timeout * 1000), wait_until="domcontentloaded")
            await page.click(selector)
            await page.wait_for_timeout(int(wait * 1000))
            html = await page.content()
            text = await page.evaluate("() => document.body.innerText")
            title = await page.title()
            final_url = page.url
        finally:
            await page.close()
        return Page(url=url, status=200, html=html, text=text, title=title, final_url=final_url)

    async def fill_form(self, url: str, fields: dict[str, str], submit_selector: str | None = None) -> Page:
        """Fill a form on a URL and optionally submit it."""
        if not self._use_pw:
            raise RuntimeError("fill_form() requires Playwright")
        if self._pw_browser is None:
            from playwright.async_api import async_playwright  # type: ignore[import-not-found]
            self._pw = await async_playwright().start()
            self._pw_browser = await self._pw.chromium.launch(headless=True)

        page = await self._pw_browser.new_page()
        try:
            await page.goto(url, timeout=int(self.timeout * 1000), wait_until="domcontentloaded")
            for selector, value in fields.items():
                await page.fill(selector, value)
            if submit_selector:
                await page.click(submit_selector)
                await page.wait_for_load_state("networkidle")
            html = await page.content()
            text = await page.evaluate("() => document.body.innerText")
            title = await page.title()
            final_url = page.url
        finally:
            await page.close()
        return Page(url=url, status=200, html=html, text=text, title=title, final_url=final_url)

    # ------------------------------------------------------------------
    #  Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the browser backend if open."""
        if self._pw_browser is not None:
            await self._pw_browser.close()
            self._pw_browser = None
        if hasattr(self, "_pw") and self._pw is not None:
            await self._pw.stop()
            self._pw = None


# ---------------------------------------------------------------------------
#  Singleton
# ---------------------------------------------------------------------------

_default_browser: Browser | None = None


def get_browser() -> Browser:
    global _default_browser
    if _default_browser is None:
        _default_browser = Browser()
    return _default_browser


__all__ = ["Browser", "Page", "get_browser"]
