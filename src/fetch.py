"""
Safe URL fetcher: allowlist, HTTP limits, text extraction.
For research use — Michelson/Feynman follow-up on search results.
"""

import re
import time
from urllib.parse import urlparse

import httpx
import trafilatura

from . import allowlist


# Limits
TIMEOUT_SEC = 10
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_REDIRECTS = 3
DRAIN_INTERVAL_SEC = 5.0

USER_AGENT = (
    "Steenbok-fetcher/1.0 (research; +https://github.com/SCantley/steenbok)"
)

# Block these schemes
BLOCKED_SCHEMES = frozenset({"file", "data", "javascript", "vbscript", "ftp"})

# Private/local IP patterns
PRIVATE_IP_PATTERN = re.compile(
    r"^(localhost|127\.|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|::1$)",
    re.IGNORECASE,
)


class FetchError(Exception):
    """Base for fetch failures."""

    pass


class AllowlistError(FetchError):
    """URL not on allowlist."""

    pass


class URLBlockedError(FetchError):
    """URL blocked by scheme or host rules."""

    pass


class ExtractionError(FetchError):
    """Could not extract text from response."""

    pass


def _is_blocked_host(host: str) -> bool:
    """Block localhost and private IPs."""
    if not host:
        return True
    return bool(PRIVATE_IP_PATTERN.match(host))


def _validate_url(url: str) -> None:
    """Raise URLBlockedError if URL is dangerous."""
    try:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").lower()
    except Exception as e:
        raise URLBlockedError(f"Invalid URL: {e}") from e

    if scheme in BLOCKED_SCHEMES:
        raise URLBlockedError(f"Blocked scheme: {scheme}")

    if scheme not in ("http", "https"):
        raise URLBlockedError(f"Unsupported scheme: {scheme}")

    if _is_blocked_host(host):
        raise URLBlockedError(f"Blocked host: {host}")

    if len(url) > 2048:
        raise URLBlockedError("URL too long")


_last_fetch_time: float = 0


def _rate_limit() -> None:
    """Enforce ~5 seconds between fetches."""
    global _last_fetch_time
    now = time.monotonic()
    elapsed = now - _last_fetch_time
    if elapsed < DRAIN_INTERVAL_SEC and _last_fetch_time > 0:
        sleep_time = DRAIN_INTERVAL_SEC - elapsed
        time.sleep(sleep_time)
    _last_fetch_time = time.monotonic()


def _extract_text(html: str, url: str) -> str:
    """Extract main text using trafilatura. Fallback to simple strip."""
    result = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        no_fallback=False,
    )
    if result and result.strip():
        return result.strip()

    # Fallback: strip tags crudely
    from html import unescape

    import re
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = unescape(text).strip()
    return text if text else ""


def fetch(url: str) -> str:
    """
    Fetch URL and return main text. Blocks until complete.
    Raises AllowlistError, URLBlockedError, or FetchError on failure.
    """
    _validate_url(url)
    if not allowlist.is_allowed(url):
        raise AllowlistError(f"URL not on allowlist: {url}")

    _rate_limit()

    try:
        with httpx.Client(
            timeout=TIMEOUT_SEC,
            max_redirects=MAX_REDIRECTS,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = client.get(
                url,
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()

            # Enforce size limit
            content = response.content
            if len(content) > MAX_RESPONSE_BYTES:
                content = content[:MAX_RESPONSE_BYTES]

            html = content.decode("utf-8", errors="replace")
    except httpx.HTTPStatusError as e:
        raise FetchError(f"HTTP {e.response.status_code}: {url}") from e
    except httpx.RequestError as e:
        raise FetchError(f"Request failed: {e}") from e

    text = _extract_text(html, url)
    if not text:
        raise ExtractionError(f"No extractable text: {url}")

    return text
