# Security Assessment: Steenbok Safe Fetch v1

**Date:** 2026-02-20
**Scope:** `src/allowlist.py`, `src/fetch.py`, `src/cli.py`
**Status:** Open — Risks 1 and 2 require remediation before production use

---

## Risk 1: SSRF via redirect chain — Severity: 5/5

The allowlist and URL validation run before the HTTP request. Then httpx follows up to 3 redirects automatically. A page on an allowlisted domain can redirect to any destination — including localhost, internal IPs, or cloud metadata endpoints.

**Example:** A compromised page on a `*.edu` server returns `302 -> http://169.254.169.254/latest/meta-data/` (AWS metadata). The allowlist passed on the original URL; the redirect is never checked.

**Location:** `src/fetch.py` lines 132-141

**Fix:** Disable automatic redirects and handle them manually, re-validating each hop against the allowlist and private-IP blocklist. Alternatively, use an httpx event hook to intercept redirects before they are followed.

---

## Risk 2: Incomplete private IP blocking — Severity: 4/5

The regex misses several private/reserved IP ranges:

- `0.0.0.0` — binds to all interfaces on many systems
- `169.254.x.x` — link-local (cloud metadata lives at 169.254.169.254)
- `fc00::/7`, `fe80::/10` — IPv6 private and link-local
- `::ffff:127.0.0.1` — IPv4-mapped IPv6 (bypasses IPv4 checks entirely)
- `[::1]` — bracketed IPv6 in URLs

The `169.254.169.254` gap is especially dangerous combined with Risk 1 (redirect SSRF).

**Location:** `src/fetch.py` lines 30-33

**Fix:** Use Python's `ipaddress` module to parse resolved IPs and check `is_private`, `is_loopback`, `is_link_local`, `is_reserved` instead of regex matching.

---

## Risk 3: Overly broad wildcard patterns — Severity: 3/5

`*.edu` matches every subdomain of every `.edu` institution — tens of thousands of servers. Same for `*.ac.uk`. Any compromised page, student personal web space, or misconfigured dev server on any university domain passes the allowlist.

**Location:** `src/allowlist.py` lines 21-22

**Fix:** Replace with specific institutions (e.g. `*.mit.edu`, `*.stanford.edu`) or accept the broad wildcards as a known trade-off and document it.

---

## Risk 4: Response fully downloaded before size check — Severity: 2/5

`response.content` reads the entire response body into memory. A 500 MB response is fully downloaded and buffered, then truncated to 5 MB. Self-DoS vector if an allowlisted URL serves a large file.

**Location:** `src/fetch.py` lines 152-154

**Fix:** Use httpx streaming (`client.stream("GET", url)`) and read chunks, stopping after 5 MB.

---

## Risk 5: No Content-Type validation — Severity: 2/5

The fetcher does not check the response Content-Type before parsing. PDFs, ZIPs, images, or binary files are decoded as UTF-8 and fed to trafilatura. Wastes resources and produces garbage output. Malicious binary content could potentially trigger parser bugs in trafilatura/lxml.

**Location:** `src/fetch.py` lines 145-156

**Fix:** Check `response.headers.get("content-type", "")` and only proceed if it contains `text/html` or `text/plain`. Reject binary content types early.

---

## Risk 6: Rate limiter not thread-safe — Severity: 2/5

Module-level mutable state (`_last_fetch_time`) with no lock. Under a multi-threaded WSGI server, concurrent requests can read the same timestamp and all proceed without waiting. Currently low impact (Flask dev server is single-threaded) but a latent bug.

**Location:** `src/fetch.py` lines 89-100

**Fix:** Use `threading.Lock()` around the global state, or switch to a queue-based approach.

---

## Risk 7: No audit logging — Severity: 1/5

No record of which URLs were fetched, when, or whether they succeeded. No forensic trail if an agent fetches something unexpected or a domain is compromised.

**Fix:** Add basic structured logging: timestamp, URL, status, bytes, elapsed.

---

## Risk 8: Double URL-decoding in Flask endpoint — Severity: 1/5

Flask already URL-decodes query parameters. The explicit `unquote()` call applies a second decode. Double-decoding is a common source of filter evasion in other contexts.

**Location:** `src/cli.py` line 75

**Fix:** Remove the `unquote()` call — Flask handles decoding.

---

## Summary

| # | Risk | Severity | Effort |
|---|------|----------|--------|
| 1 | SSRF via redirect | 5/5 | Medium |
| 2 | Incomplete private IP blocking | 4/5 | Low |
| 3 | Overly broad wildcards | 3/5 | Low |
| 4 | Full download before size check | 2/5 | Low |
| 5 | No Content-Type validation | 2/5 | Low |
| 6 | Rate limiter not thread-safe | 2/5 | Low |
| 7 | No audit logging | 1/5 | Low |
| 8 | Double URL-decoding | 1/5 | Trivial |

## Recommendation

Fix Risks 1 and 2 before any agent uses this in production. Risks 3-6 should be addressed in v1.1. Risks 7-8 are low-priority improvements.
