"""Tests for allowlist module."""

from src import allowlist


def test_default_allows_wikipedia():
    allowlist.reset_cache()
    assert allowlist.is_allowed("https://en.wikipedia.org/wiki/Test")
    assert allowlist.is_allowed("https://en.wikipedia.org/wiki/Steenbok")


def test_default_allows_arxiv():
    allowlist.reset_cache()
    assert allowlist.is_allowed("https://arxiv.org/abs/2401.12345")


def test_default_allows_ncbi_subdomain():
    allowlist.reset_cache()
    assert allowlist.is_allowed("https://pubmed.ncbi.nlm.nih.gov/12345")
    assert allowlist.is_allowed("https://www.ncbi.nlm.nih.gov/gene/123")


def test_default_denies_example_com():
    allowlist.reset_cache()
    assert not allowlist.is_allowed("https://example.com/page")


def test_denies_file_scheme():
    allowlist.reset_cache()
    assert not allowlist.is_allowed("file:///etc/passwd")


def test_denies_data_scheme():
    allowlist.reset_cache()
    assert not allowlist.is_allowed("data:text/html,<script>alert(1)</script>")


def test_denies_javascript_scheme():
    allowlist.reset_cache()
    assert not allowlist.is_allowed("javascript:alert(1)")


def test_denies_localhost():
    allowlist.reset_cache()
    assert not allowlist.is_allowed("https://localhost/admin")
    assert not allowlist.is_allowed("https://127.0.0.1/test")


def test_denies_invalid_url():
    allowlist.reset_cache()
    assert not allowlist.is_allowed("not-a-url")
    assert not allowlist.is_allowed("")

