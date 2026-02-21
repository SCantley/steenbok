"""
Safe URL fetcher: allowlist, HTTP limits, text extraction.
For research use — Michelson/Feynman follow-up on search results.
"""

import ipaddress
import logging
import os
import re
import socket
import threading
import time
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

from . import allowlist

# Audit logger: ISO 8601 timestamp on every entry
_LOG = logging.getLogger("steenbok.fetch")
if not _LOG.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s.%(msecs)03dZ [steenbok] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    _handler.formatter.converter = time.gmtime
    _LOG.addHandler(_handler)
    _LOG.setLevel(logging.INFO)


# Limits
TIMEOUT_SEC = 10
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_PDF_BYTES = 2 * 1024 * 1024  # 2 MB — stricter cap before PyMuPDF parsing
MAX_REDIRECTS = 3
DRAIN_INTERVAL_SEC = 5.0

USER_AGENT = (
    "Steenbok-fetcher/1.0 (research; +https://github.com/SCantley/steenbok)"
)

# Block these schemes
BLOCKED_SCHEMES = frozenset({"file", "data", "javascript", "vbscript", "ftp"})

# Hostnames to block without DNS resolution
BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})


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


def _is_blocked_ip(ip_str: str) -> bool:
    """
    Return True if the given IP (string) is private, loopback, link-local,
    reserved, or unspecified. Uses ipaddress module for full coverage
    (0.0.0.0, 169.254.x.x, IPv6 private/link-local, IPv4-mapped IPv6).
    Returns False for non-IP strings (hostnames) — they are validated by allowlist.
    """
    try:
        addr = ipaddress.ip_address(ip_str.strip())
    except ValueError:
        return False  # Not an IP (e.g. domain name); allowlist will validate
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_unspecified
    )


def _is_blocked_host(host: str) -> bool:
    """Block localhost and private/local/reserved IPs. Uses ipaddress for IP parsing."""
    if not host:
        return True
    host_lower = host.lower().strip()
    # Strip brackets from IPv6 URLs, e.g. [::1] -> ::1
    if host_lower.startswith("[") and host_lower.endswith("]"):
        host_lower = host_lower[1:-1]
    if host_lower in BLOCKED_HOSTNAMES:
        return True
    return _is_blocked_ip(host_lower)


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

    if scheme == "http" and os.environ.get("STEENBOK_ALLOW_HTTP", "") != "1":
        raise URLBlockedError("HTTP not allowed; set STEENBOK_ALLOW_HTTP=1 to permit")

    if _is_blocked_host(host):
        raise URLBlockedError(f"Blocked host: {host}")

    if len(url) > 2048:
        raise URLBlockedError("URL too long")


def _resolve_and_validate_host(host: str) -> None:
    """
    Resolve host to IPs and raise URLBlockedError if any resolve to private/local.
    Used for both initial fetch and redirect targets to prevent DNS rebinding.
    """
    if not host:
        raise URLBlockedError("Host has no hostname")

    try:
        for res in socket.getaddrinfo(host, None, socket.AF_UNSPEC):
            sockaddr = res[4]
            if res[0] == socket.AF_INET:
                ip_str = sockaddr[0]
            elif res[0] == socket.AF_INET6:
                ip_str = sockaddr[0]
            else:
                continue
            if _is_blocked_ip(ip_str):
                raise URLBlockedError(f"Resolves to blocked IP: {ip_str}")
    except socket.gaierror as e:
        raise URLBlockedError(f"Host unreachable: {host}") from e

    if _is_blocked_host(host):
        raise URLBlockedError(f"Blocked host: {host}")


def _validate_redirect_target(redirect_url: str, current_url: str) -> None:
    """
    Validate a redirect target: allowlist, URL rules, and resolved IP blocklist.
    Raises URLBlockedError or AllowlistError if invalid.
    """
    parsed = urlparse(redirect_url)
    host = (parsed.hostname or "").lower()
    if not host:
        raise URLBlockedError("Redirect target has no host")

    _resolve_and_validate_host(host)

    # Allowlist: redirect target must be on allowlist
    if not allowlist.is_allowed(redirect_url):
        raise AllowlistError(f"Redirect target not on allowlist: {redirect_url}")


_last_fetch_time: float = 0
_rate_limit_lock = threading.Lock()


def _rate_limit() -> None:
    """Enforce ~5 seconds between fetches. Thread-safe for multi-threaded WSGI.
    Lock released before sleep so concurrent requests do not queue for full duration.
    """
    global _last_fetch_time
    while True:
        with _rate_limit_lock:
            now = time.monotonic()
            elapsed = now - _last_fetch_time
            if elapsed >= DRAIN_INTERVAL_SEC or _last_fetch_time == 0:
                _last_fetch_time = time.monotonic()
                return
            sleep_time = DRAIN_INTERVAL_SEC - elapsed
        time.sleep(sleep_time)


def _extract_text_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF using PyMuPDF. Returns empty string if no text."""
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise ExtractionError("PDF exceeds maximum size")

    import fitz  # PyMuPDF

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            text = "".join(page.get_text() for page in doc)
            return text.strip() if text.strip() else ""
        finally:
            doc.close()
    except Exception:
        raise ExtractionError("PDF could not be read (corrupted, encrypted, or unsupported)")


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


def _do_fetch(
    client: httpx.Client, url: str
) -> tuple[httpx.Response, bytes]:
    """
    Perform GET with manual redirect handling. Validates each redirect target
    against allowlist and IP blocklist. Streams body, stopping at MAX_RESPONSE_BYTES.
    Returns (response, content).
    """
    current_url = url
    redirect_count = 0

    while redirect_count <= MAX_REDIRECTS:
        with client.stream(
            "GET", current_url, follow_redirects=False
        ) as response:
            if 300 <= response.status_code < 400:
                # Drain redirect response body before reconnecting
                for _ in response.iter_bytes():
                    pass
                redirect_count += 1
                if redirect_count > MAX_REDIRECTS:
                    raise FetchError(f"Too many redirects: {url}")
                location = response.headers.get("location")
                if not location:
                    raise FetchError("Redirect without Location header")
                redirect_url = urljoin(str(response.url), location)
                _validate_redirect_target(redirect_url, current_url)
                current_url = redirect_url
                continue

            response.raise_for_status()

            # Stream and enforce size limit (Risk 4)
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > MAX_RESPONSE_BYTES:
                    break
            return response, bytes(content)

    raise FetchError(f"Too many redirects: {url}")  # Unreachable


def fetch(url: str) -> str:
    """
    Fetch URL and return main text. Blocks until complete.
    Raises AllowlistError, URLBlockedError, or FetchError on failure.
    """
    start_time = time.monotonic()

    try:
        _validate_url(url)
    except URLBlockedError as e:
        _LOG.info("reason=url_blocked url=%s error=%s", url, e)
        raise

    if not allowlist.is_allowed(url):
        _LOG.info("reason=allowlist_violation url=%s", url)
        raise AllowlistError(f"URL not on allowlist: {url}")

    # DNS rebinding protection: resolve initial host before first HTTP request
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host:
        _resolve_and_validate_host(host)

    _rate_limit()

    try:
        with httpx.Client(
            timeout=TIMEOUT_SEC,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response, content = _do_fetch(client, url)
            elapsed = time.monotonic() - start_time

            # Content-Type validation (Risk 5)
            content_type = (response.headers.get("content-type") or "").lower()
            if "application/msword" in content_type:
                raise FetchError(f"Blocked content type: {content_type}")
            if "application/vnd.ms-" in content_type:
                raise FetchError(f"Blocked content type: {content_type}")
            if "application/vnd.openxmlformats-officedocument" in content_type:
                raise FetchError(f"Blocked content type: {content_type}")
            if "application/rtf" in content_type:
                raise FetchError(f"Blocked content type: {content_type}")
            if any(
                x in content_type
                for x in ("application/zip", "application/x-rar", "application/x-7z")
            ):
                raise FetchError(f"Blocked content type: {content_type}")
            if "image/svg+xml" in content_type:
                raise FetchError(f"Blocked content type: {content_type}")
            if "application/javascript" in content_type:
                raise FetchError(f"Blocked content type: {content_type}")
            if "application/x-msdownload" in content_type:
                raise FetchError(f"Blocked content type: {content_type}")

            if "application/pdf" in content_type:
                text = _extract_text_pdf(content)
            elif (
                "text/html" in content_type
                or "text/plain" in content_type
                or "application/xhtml+xml" in content_type
            ):
                html = content.decode("utf-8", errors="replace")
                text = _extract_text(html, url)
            else:
                raise FetchError(f"Unsupported content type: {content_type}")

        if not text:
            raise ExtractionError(f"No extractable text: {url}")

        _LOG.info(
            "reason=success url=%s status=%s bytes=%s elapsed_sec=%.3f",
            url,
            response.status_code,
            len(content),
            elapsed,
        )
        return text

    except httpx.HTTPStatusError as e:
        elapsed = time.monotonic() - start_time
        _LOG.info(
            "reason=fetch_failed url=%s error=%s elapsed_sec=%.3f",
            url,
            str(e),
            elapsed,
        )
        raise FetchError(f"HTTP {e.response.status_code}: {url}") from e
    except httpx.RequestError as e:
        elapsed = time.monotonic() - start_time
        _LOG.info(
            "reason=fetch_failed url=%s error=%s elapsed_sec=%.3f",
            url,
            str(e),
            elapsed,
        )
        raise FetchError(f"Request failed: {e}") from e
    except (FetchError, ExtractionError) as e:
        elapsed = time.monotonic() - start_time
        _LOG.info(
            "reason=fetch_failed url=%s error=%s elapsed_sec=%.3f",
            url,
            str(e),
            elapsed,
        )
        raise
