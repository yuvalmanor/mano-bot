"""Mocked unit tests for integrations.web (fetch_url + HTML→text + SSRF guard)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from integrations import web


def _resp(status_code: int, text: str = "", content_type: str = "text/html") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.headers = {"content-type": content_type}
    return r


def _client_returning(resp_or_exc):
    """Patch httpx.AsyncClient so .get returns resp_or_exc (or raises if Exception)."""
    client = MagicMock()
    if isinstance(resp_or_exc, Exception):
        client.get = AsyncMock(side_effect=resp_or_exc)
    else:
        client.get = AsyncMock(return_value=resp_or_exc)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return patch("integrations.web.httpx.AsyncClient", return_value=cm), client


# ---- html_to_text ----------------------------------------------------------


def test_html_to_text_strips_tags_and_scripts() -> None:
    html = (
        "<html><head><style>.x{}</style></head><body>"
        "<h1>Wineries</h1><script>evil()</script>"
        "<p>Tishbi open Saturday</p><p>Recanati open Saturday</p>"
        "</body></html>"
    )
    text = web.html_to_text(html)
    assert "Wineries" in text
    assert "Tishbi open Saturday" in text
    assert "Recanati open Saturday" in text
    assert "evil()" not in text
    assert ".x{}" not in text


def test_html_to_text_truncates() -> None:
    html = "<p>" + ("a" * (web.MAX_TEXT_CHARS + 500)) + "</p>"
    text = web.html_to_text(html)
    assert len(text) <= web.MAX_TEXT_CHARS + len("\n…[truncated]")
    assert text.endswith("[truncated]")


# ---- SSRF guard -------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "not a url",
        "",
    ],
)
@pytest.mark.asyncio
async def test_fetch_url_blocks_unsafe(url: str) -> None:
    # No client patch needed — guard should short-circuit before any request.
    assert await web.fetch_url(url) == ""


@pytest.mark.asyncio
async def test_fetch_url_allows_public_host() -> None:
    cm, client = _client_returning(_resp(200, "<p>hello world</p>"))
    with cm:
        text = await web.fetch_url("https://example.com/article")
    assert "hello world" in text
    client.get.assert_awaited_once()


# ---- fetch_url error handling ----------------------------------------------


@pytest.mark.asyncio
async def test_fetch_url_http_error_returns_empty() -> None:
    cm, _ = _client_returning(_resp(404, "nope"))
    with cm:
        assert await web.fetch_url("https://example.com/missing") == ""


@pytest.mark.asyncio
async def test_fetch_url_timeout_returns_empty() -> None:
    cm, _ = _client_returning(httpx.TimeoutException("slow"))
    with cm:
        assert await web.fetch_url("https://example.com/slow") == ""


@pytest.mark.asyncio
async def test_fetch_url_non_html_returned_as_text() -> None:
    cm, _ = _client_returning(
        _resp(200, "plain text body", content_type="text/plain")
    )
    with cm:
        text = await web.fetch_url("https://example.com/raw.txt")
    assert "plain text body" in text
