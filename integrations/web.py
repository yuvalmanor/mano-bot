"""Web fetch integration.

Fetches a URL and returns readable plain text, so the agent can read article
links the user wants to store in (or recall from) the Idea Lab knowledge DB.

Design choices mirror the other integrations:
* httpx with a 10-second timeout; transport/HTTP errors are caught and turned
  into an empty string (never raised to the caller).
* HTML is reduced to text with the stdlib ``html.parser`` — no BeautifulSoup,
  so nothing new to pip install (keeps this 🟢 under the SentinelOne protocol).
* A small SSRF guard rejects non-http(s) schemes and private/loopback hosts so
  an attacker-supplied link can't make the server poke internal addresses.

Permission checks happen at the ``claude_agent`` dispatch layer, not here.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from security.audit import log_action

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
# A realistic browser User-Agent + Accept headers. News/tech sites behind a
# WAF/CDN (Cloudflare, Incapsula) frequently 403 an obvious bot UA when the
# request comes from a datacenter IP (e.g. Railway). Looking like a browser
# clears the common static checks.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
}
# Cap on returned text so it's safe to feed back into the model context.
MAX_TEXT_CHARS = 8000
# Cap on bytes we read off the wire before parsing (defensive against huge pages).
MAX_FETCH_BYTES = 3_000_000

# Tags whose text content is noise, not article body.
_SKIP_TAGS = {"script", "style", "noscript", "template", "head"}
# Block-level tags that should introduce a line break in the extracted text.
_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "ul", "ol", "table",
    "blockquote", "pre",
}


class _TextExtractor(HTMLParser):
    """Collect visible text from HTML, dropping script/style and adding breaks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _collapse_whitespace(text: str) -> str:
    """Trim each line and drop blank-line runs, preserving paragraph breaks."""
    lines = [line.strip() for line in text.splitlines()]
    out: list[str] = []
    blank = False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def html_to_text(html: str) -> str:
    """Reduce an HTML document to collapsed, readable plain text (capped)."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # malformed HTML — keep whatever we extracted so far
        logger.debug("html_to_text parser error; using partial output")
    text = _collapse_whitespace(parser.get_text())
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS].rstrip() + "\n…[truncated]"
    return text


def _is_blocked_host(host: str) -> bool:
    """True if ``host`` is loopback/private/link-local (SSRF guard)."""
    if not host:
        return True
    host = host.strip().lower().strip("[]")
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Not a bare IP — a regular hostname. Allow (DNS rebinding is out of
        # scope for this single-user, authorized-caller feature).
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def _is_safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return not _is_blocked_host(parsed.hostname or "")


async def fetch_url(url: str) -> str:
    """Fetch ``url`` and return readable plain text. Empty string on any failure.

    Rejects non-http(s) schemes and private/loopback hosts. Non-HTML responses
    are returned as-is (still capped). Logs an audit line with the outcome.
    """
    url = (url or "").strip()
    if not _is_safe_url(url):
        log_action("", "web_fetch_url", "", "blocked")
        return ""

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            resp = await client.get(url, headers=_BROWSER_HEADERS)
        if resp.status_code >= 400:
            logger.error("web fetch_url HTTP %s", resp.status_code)
            log_action("", "web_fetch_url", "", f"http_{resp.status_code}")
            return ""
        raw = resp.text[:MAX_FETCH_BYTES]
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("web fetch_url error: %s", exc.__class__.__name__)
        log_action("", "web_fetch_url", "", "error")
        return ""

    content_type = resp.headers.get("content-type", "")
    if "html" in content_type or re.search(r"<\s*html", raw[:2000], re.IGNORECASE):
        text = html_to_text(raw)
    else:
        text = _collapse_whitespace(raw)
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS].rstrip() + "\n…[truncated]"

    log_action("", "web_fetch_url", "", "ok" if text else "empty")
    return text
