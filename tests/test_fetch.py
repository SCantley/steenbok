"""Tests for fetch module (IP blocking, validation)."""

import pytest

from src.fetch import (
    AllowlistError,
    ExtractionError,
    FetchError,
    URLBlockedError,
    _is_blocked_host,
    _is_blocked_ip,
    fetch,
)


def test_blocked_ip_169_254():
    """Link-local (cloud metadata) must be blocked."""
    assert _is_blocked_ip("169.254.169.254") is True
    assert _is_blocked_ip("169.254.0.1") is True


def test_blocked_ip_0_0_0_0():
    """Unspecified address must be blocked."""
    assert _is_blocked_ip("0.0.0.0") is True


def test_blocked_ip_private_ranges():
    """Standard private ranges must be blocked."""
    assert _is_blocked_ip("10.0.0.1") is True
    assert _is_blocked_ip("192.168.1.1") is True
    assert _is_blocked_ip("172.16.0.1") is True


def test_blocked_ip_loopback():
    """Loopback must be blocked."""
    assert _is_blocked_ip("127.0.0.1") is True
    assert _is_blocked_ip("::1") is True


def test_blocked_host_localhost():
    """Localhost hostname must be blocked."""
    assert _is_blocked_host("localhost") is True
    assert _is_blocked_host("LOCALHOST") is True


def test_blocked_host_ipv6_bracketed():
    """Bracketed IPv6 in URLs must be blocked."""
    assert _is_blocked_host("[::1]") is True


def test_allowed_ip_public():
    """Public IPs must not be blocked."""
    assert _is_blocked_ip("8.8.8.8") is False
    assert _is_blocked_ip("1.1.1.1") is False


def test_fetch_allowlist_violation():
    """Fetching non-allowlisted URL raises AllowlistError."""
    from src import allowlist

    allowlist.reset_cache()
    with pytest.raises(AllowlistError, match="not on allowlist"):
        fetch("https://example.com/page")


def test_fetch_blocked_host():
    """Fetching localhost raises URLBlockedError."""
    with pytest.raises(URLBlockedError, match="Blocked host"):
        fetch("https://127.0.0.1/admin")
