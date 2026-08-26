"""Tests for the Browser module."""

from __future__ import annotations

import pytest

from aion_core.browser import Browser, Page, get_browser


class TestBrowserInit:
    """Verify Browser constructs without crashing."""

    def test_browser_instantiable(self):
        b = Browser(use_playwright=False)  # force urllib mode
        assert b is not None
        assert b.backend == "urllib"

    def test_browser_singleton(self):
        b1 = get_browser()
        b2 = get_browser()
        assert b1 is b2


class TestStdlibParsing:
    """Verify the stdlib HTML parsers work correctly."""

    @pytest.mark.asyncio
    async def test_fetch_text_extracts_visible_text(self):
        # Use a data: URL-style test — we'll mock by calling internal helpers
        b = Browser(use_playwright=False)
        # Manually construct a Page and verify the parsers work
        html = """
        <html><head><title>Test Page</title></head>
        <body>
            <script>var x = 1;</script>
            <style>body { color: red; }</style>
            <h1>Hello World</h1>
            <p>This is a paragraph.</p>
            <a href="/about">About Us</a>
            <a href="https://example.com">External</a>
            <meta name="description" content="A test page">
        </body></html>
        """
        # Use the internal parsers directly
        from aion_core.browser import _TextExtractor, _LinkExtractor, _TitleExtractor, _MetaExtractor
        te = _TextExtractor()
        te.feed(html)
        text = te.get_text()
        assert "Hello World" in text
        assert "This is a paragraph" in text
        # Scripts and styles should be excluded
        assert "var x = 1" not in text
        assert "color: red" not in text

        le = _LinkExtractor()
        le.feed(html)
        assert len(le.links) == 2

        tie = _TitleExtractor()
        tie.feed(html)
        assert tie.title == "Test Page"

        me = _MetaExtractor()
        me.feed(html)
        assert me.meta.get("description") == "A test page"


class TestPageDataclass:
    """Page dataclass behaviour."""

    def test_page_to_dict(self):
        p = Page(
            url="https://example.com",
            status=200,
            html="<html></html>",
            text="Hello world",
            title="Example",
            links=[("https://example.com/about", "About")],
            meta={"description": "An example"},
        )
        d = p.to_dict()
        assert d["url"] == "https://example.com"
        assert d["status"] == 200
        assert d["title"] == "Example"
        assert d["text_length"] == len("Hello world")
        assert d["links_count"] == 1
        assert d["text_preview"] == "Hello world"


class TestBrowserLiveFetch:
    """Live network tests (skipped if offline)."""

    @pytest.mark.asyncio
    async def test_fetch_example_com(self):
        # example.com is rock-solid and serves simple HTML
        b = Browser(use_playwright=False, timeout=10.0)
        try:
            page = await b.fetch("https://example.com")
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Network unavailable: {exc}")
        assert page.status == 200
        assert "Example Domain" in page.title or "Example" in page.text
        assert len(page.text) > 0
