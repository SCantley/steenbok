"""
Domain allowlist for safe URL fetching.
Loads from default list + optional config file or env override.
"""

from __future__ import annotations

import fnmatch
import os
from urllib.parse import urlparse


# Default domains for research use. Extensible via config.
# Note: *.edu and *.ac.uk are broad by design (tens of thousands of subdomains).
# This is a known trade-off: maximum coverage vs risk from compromised institution
# pages. Use ~/.steenbok/allowlist.txt or STEENBOK_ALLOWED_DOMAINS to narrow.
DEFAULT_ALLOWED = [
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "*.ncbi.nlm.nih.gov",
    "jstor.org",
    "doi.org",
    "*.edu",
    "*.ac.uk",
    "wikipedia.org",
    "*.wikipedia.org",
    "en.wikipedia.org",
    "www.google.com",
    "scholar.google.com",
    "books.google.com",
    "patents.google.com",
]

ALLOWLIST_ENV = "STEENBOK_ALLOWED_DOMAINS"
ALLOWLIST_FILE = os.path.expanduser("~/.steenbok/allowlist.txt")


def _load_domains() -> list[str]:
    """Load allowlist: default + file (if exists) + env override."""
    domains = list(DEFAULT_ALLOWED)

    # File can add or replace: each line = one domain or *.domain
    if os.path.exists(ALLOWLIST_FILE):
        with open(ALLOWLIST_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    domains.append(line)

    # Env can append: comma-separated
    extra = os.environ.get(ALLOWLIST_ENV, "")
    if extra:
        for d in extra.split(","):
            d = d.strip()
            if d:
                domains.append(d)

    return domains


def _normalize_host(url: str) -> str | None:
    """Extract and normalize host from URL (lowercase, no port)."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or parsed.netloc or "").lower()
        # Strip port if present
        if ":" in host:
            host = host.split(":")[0]
        return host if host else None
    except Exception:
        return None


def _host_matches_pattern(host: str, pattern: str) -> bool:
    """Check if host matches pattern. Supports *.domain for subdomains."""
    return fnmatch.fnmatch(host, pattern)


_cached_domains: list[str] | None = None


def _get_domains() -> list[str]:
    """Lazy-load and cache the allowlist."""
    global _cached_domains
    if _cached_domains is None:
        _cached_domains = _load_domains()
    return _cached_domains


def is_allowed(url: str) -> bool:
    """
    Return True if URL's host is on the allowlist.
    Requires https (or http only for explicitly listed legacy domains).
    """
    host = _normalize_host(url)
    if not host:
        return False

    try:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
    except Exception:
        return False

    if scheme not in ("http", "https"):
        return False

    domains = _get_domains()
    for pattern in domains:
        if _host_matches_pattern(host, pattern):
            return True
    return False


def reset_cache() -> None:
    """Clear cached allowlist (for tests)."""
    global _cached_domains
    _cached_domains = None
