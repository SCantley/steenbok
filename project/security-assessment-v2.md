# Security Assessment v2: Steenbok Safe Fetch

**Date:** 2026-02-20
**Scope:** `src/fetch.py`, `src/cli.py`, `src/allowlist.py`, `requirements.txt`, `.gitignore`
**Assessor:** Automated review (Claude)
**Prior assessment:** `project/plans.bak/security-assessment-v1.md` (8 risks, all remediated)

---

## Executive Summary

The v1 assessment identified 8 risks (SSRF via redirects, incomplete IP blocking,
broad wildcards, unbounded downloads, missing Content-Type checks, thread-unsafe rate
limiter, no audit logging, double URL-decoding). **All 8 have been remediated** in the
current codebase. The code quality is strong: manual redirect handling, `ipaddress`-based
IP blocking, streaming downloads, Content-Type validation, thread-safe rate limiting,
and structured audit logging are all in place.

This v2 assessment identifies **9 new or residual risks** on a 1–10 severity scale.

---

## Risk 1: DNS Rebinding on Initial Fetch — Severity: 7/10

**What:** Redirect targets are correctly DNS-resolved and checked against the IP
blocklist (`_validate_redirect_target` at fetch.py:130–163). However, the *initial*
request to the user-supplied URL is **not** DNS-resolved before connecting. The flow is:

1. `_validate_url()` — checks scheme, hostname string, URL length
2. `allowlist.is_allowed()` — checks hostname against domain patterns
3. `httpx.Client.stream("GET", url)` — connects to whatever IP DNS returns **now**

Between steps 2 and 3, an attacker controlling DNS for a subdomain of an allowlisted
domain (e.g., `evil.mit.edu` under `*.edu`) can resolve it to `169.254.169.254` or
`127.0.0.1`. The allowlist passes because the domain matches `*.edu`; the IP is never
checked for the first hop.

**Impact:** SSRF to cloud metadata endpoints, internal services, or localhost. This is
the same class of attack as v1 Risk 1, but on the initial request rather than redirects.

**Location:** `src/fetch.py` — `fetch()` function, lines 263–288. No DNS resolution
occurs before the first `client.stream()` call.

**Remediation:** Add a DNS resolution + IP blocklist check to `fetch()` before the first
HTTP request, mirroring the logic already in `_validate_redirect_target()`. Extract the
shared logic into a helper like `_resolve_and_validate_host(hostname)`.

---

## Risk 2: Overly Permissive Google Wildcards — Severity: 6/10

**What:** The default allowlist includes both `google.com` and `*.google.com`. This
matches far more than the intended research use cases:

- `sites.google.com` — anyone can create a Google Site with arbitrary content
- `drive.google.com` / `docs.google.com` — shared documents with untrusted content
- `translate.google.com` — acts as an open proxy (`translate.google.com/translate?u=...`)
- `feedproxy.google.com` — redirects to arbitrary URLs

A malicious actor could craft a Google Translate URL that proxies a request to an
internal resource, or host malicious content on Google Sites that an agent then fetches
and trusts.

**Impact:** Allowlist bypass via Google services acting as open redirectors/proxies.
Untrusted content from attacker-controlled Google Sites treated as "allowlisted."

**Location:** `src/allowlist.py` lines 29–30

**Remediation:** Replace `google.com` and `*.google.com` with the specific Google
services needed for research:
- `www.google.com` — standard web search
- `scholar.google.com` — academic search
- `books.google.com` — book previews and citations
- `patents.google.com` — patent research

---

## Risk 3: Untrusted PDF Parsing (PyMuPDF) — Severity: 5/10

**What:** `_extract_text_pdf()` passes attacker-controlled bytes directly to PyMuPDF's
`fitz.open()`. PDF parsers are historically a rich source of memory corruption
vulnerabilities (CVEs in MuPDF, Poppler, etc.). A crafted PDF from an allowlisted domain
could trigger a parser bug leading to crashes or, in worst case, code execution.

The current code wraps the call in a try/except that catches `Exception`, but memory
corruption bugs bypass Python exception handling.

**Impact:** Denial of service (crash). Potential code execution if a MuPDF vulnerability
exists.

**Location:** `src/fetch.py` lines 181–193

**Remediation:**
- Keep PyMuPDF updated (pin to latest patch version)
- Consider running PDF parsing in a subprocess with resource limits (`ulimit`, timeout)
- Add a maximum PDF size check before parsing (current 5 MB limit helps but is generous
  for PDFs)

---

## Risk 4: Unused Dangerous Dependency (browser-cookie3) — Severity: 5/10

**What:** `browser-cookie3>=0.19.0` is listed in `requirements.txt` but is **not
imported or used** anywhere in the current source code. This library reads browser cookie
databases (Safari, Chrome, Firefox), which means it has access to authentication tokens
for every site the user is logged into.

An unused dependency with this level of privilege is a supply chain risk: if a
compromised version is published to PyPI, it would be installed into the Steenbok
environment with access to all browser cookies, and the compromise would go unnoticed
since the library isn't actively called.

**Impact:** Supply chain attack vector. A compromised `browser-cookie3` release could
exfiltrate browser session cookies.

**Location:** `requirements.txt` line 4

**Remediation:** Remove `browser-cookie3` from `requirements.txt` if it is not currently
needed. If planned for future use, move it to a separate `requirements-browser.txt` and
only install it when that feature is activated.

---

## Risk 5: No HTTPS Enforcement for External Requests — Severity: 4/10

**What:** Both `http://` and `https://` schemes are allowed for all fetches. HTTP
traffic is transmitted in plaintext and is vulnerable to man-in-the-middle interception
or modification. An attacker on the same network (e.g., public WiFi, compromised router)
could inject malicious content into an HTTP response that the agent then trusts.

All domains in the default allowlist support HTTPS (arxiv.org, wikipedia.org, etc.), so
there is no functional reason to allow HTTP for these sites.

**Impact:** Content injection via MITM on HTTP connections. Agent receives and processes
attacker-modified content.

**Location:** `src/fetch.py` lines 120–121 (allows both `http` and `https`)
`src/allowlist.py` lines 104–105 (allows both `http` and `https`)

**Remediation:** Default to HTTPS-only. If HTTP support is needed for specific use cases
(e.g., local development), make it opt-in via an environment variable like
`STEENBOK_ALLOW_HTTP=1`.

---

## Risk 6: Unpinned Dependency Versions — Severity: 4/10

**What:** All dependencies in `requirements.txt` use `>=` minimum bounds with no upper
limit. A `pip install -r requirements.txt` on a fresh environment will pull the latest
version of every package. If any dependency publishes a broken or malicious release, it
is automatically installed.

Key high-privilege dependencies:
- `flask>=3.0.0` — serves HTTP
- `httpx>=0.27.0` — makes outbound HTTP requests
- `pymupdf>=1.24.0` — parses binary (PDF) content
- `trafilatura>=1.6.0` — parses untrusted HTML

**Impact:** Supply chain compromise. Broken builds from incompatible updates.

**Location:** `requirements.txt`

**Remediation:** Pin dependencies to exact versions (e.g., `flask==3.1.0`) or use
bounded ranges (e.g., `flask>=3.0.0,<4.0.0`). Generate a `requirements.lock` or use
`pip freeze` to capture resolved versions after a known-good install.

---

## Risk 7: Flask Endpoint Has No Authentication — Severity: 1/10

**What:** The `/fetch` endpoint on `127.0.0.1:8877` has no authentication mechanism. Any
process running on the local machine can call it.

**Mitigating factors:** The endpoint binds to `127.0.0.1` only (no remote access). All
requests are still constrained by the domain allowlist — a caller cannot fetch arbitrary
URLs. Every request is audit-logged with timestamp, URL, and outcome, providing a full
forensic trail. Steenbok runs exclusively on the owner's personal equipment with no
multi-user or shared-server deployment planned.

**Impact:** Minimal. A rogue local process could fetch allowlisted academic domains
through the endpoint, but this is low value and fully logged.

**Location:** `src/cli.py` lines 64–86

**Remediation:** Accepted as-is. If deployment context ever changes (shared machine,
network-exposed), revisit with a startup token or Unix domain socket.

---

## Risk 8: Error Message Information Leakage — Severity: 2/10

**What:** The Flask endpoint returns internal error details to the caller:

```python
except (ExtractionError, FetchError) as e:
    return {"error": str(e)}, 502
```

`FetchError` messages include internal details like "Redirect target resolves to blocked
IP: 169.254.169.254" or "HTTP 403: https://..." which reveal infrastructure details and
security controls to an attacker probing the endpoint.

**Impact:** Information disclosure. Attacker can map internal network topology and
security rules by observing error messages.

**Location:** `src/cli.py` line 83

**Remediation:** Return generic error messages to the HTTP client ("Fetch failed") and
log the detailed error server-side (the audit logger already captures this).

---

## Risk 9: Rate Limiter Holds Lock During Sleep — Severity: 2/10

**What:** The `_rate_limit()` function acquires `_rate_limit_lock` and then potentially
sleeps for up to 5 seconds while holding the lock:

```python
with _rate_limit_lock:
    ...
    time.sleep(sleep_time)   # Up to 5 seconds, lock held
    _last_fetch_time = time.monotonic()
```

Under a multi-threaded WSGI server (e.g., gunicorn with threads), all concurrent
requests queue behind the lock. If N requests arrive simultaneously, the last one waits
N * 5 seconds. With enough concurrent requests, this becomes a self-inflicted denial of
service.

**Impact:** Resource exhaustion / denial of service under concurrent load.

**Location:** `src/fetch.py` lines 169–178

**Remediation:** Release the lock before sleeping: calculate the required sleep time
under the lock, release it, sleep, then re-acquire to update the timestamp. Or use a
`threading.Event` / `queue.Queue` based approach that serializes requests without
holding a lock during I/O waits.

---

## Previously Identified Risks (v1) — Status

| v1 # | Risk | v1 Severity | Status |
|-------|------|-------------|--------|
| 1 | SSRF via redirect chain | 5/5 | **Remediated** — Manual redirect handling with per-hop validation |
| 2 | Incomplete private IP blocking | 4/5 | **Remediated** — `ipaddress` module with full coverage |
| 3 | Overly broad wildcards (*.edu, *.ac.uk) | 3/5 | **Accepted** — Documented as known trade-off |
| 4 | Full download before size check | 2/5 | **Remediated** — Streaming with chunked reads |
| 5 | No Content-Type validation | 2/5 | **Remediated** — Blocklist + allowlist approach |
| 6 | Rate limiter not thread-safe | 2/5 | **Remediated** — `threading.Lock()` added |
| 7 | No audit logging | 1/5 | **Remediated** — Structured logging with ISO 8601 |
| 8 | Double URL-decoding | 1/5 | **Remediated** — `unquote()` removed |

---

## Summary Table

| # | Risk | Severity (1–10) | Effort | Priority |
|---|------|-----------------|--------|----------|
| 1 | DNS rebinding on initial fetch | 7 | Low | High — same class as v1's top risk |
| 2 | Overly permissive Google wildcards | 6 | Low | High — easy fix, significant exposure |
| 3 | Untrusted PDF parsing (PyMuPDF) | 5 | Medium | Medium |
| 4 | Unused dangerous dependency (browser-cookie3) | 5 | Trivial | Medium — remove one line |
| 5 | No HTTPS enforcement | 4 | Low | Medium |
| 6 | Unpinned dependency versions | 4 | Low | Medium |
| 7 | Flask endpoint has no authentication | 1 | N/A | Accepted — localhost + allowlist + logging |
| 8 | Error message information leakage | 2 | Trivial | Low |
| 9 | Rate limiter holds lock during sleep | 2 | Low | Low |

---

## Recommendations

**Before production use (Risks 1–2):**
Risk 1 is the same vulnerability class as v1's highest-severity finding — it should be
treated with the same urgency. Risk 2 is a one-line fix that meaningfully tightens the
allowlist.

**Short-term hardening (Risks 3–6):**
Remove the unused dependency (Risk 4) immediately. Pin versions (Risk 6) on the next
dependency update. Enforce HTTPS (Risk 5) and harden PDF parsing (Risk 3) before
expanding usage.

**Operational improvements (Risks 8–9):**
Low-priority cleanup. Risk 7 is accepted given single-user, localhost-only deployment
with allowlist enforcement and audit logging.

---

## Positive Findings

The codebase demonstrates strong security awareness:

- **SSRF protection on redirects** is thorough: DNS resolution, IP blocklist, and
  allowlist re-check on every hop
- **IP blocking** uses `ipaddress` module correctly, covering IPv4, IPv6, mapped
  addresses, and bracketed notation
- **Content-Type validation** uses defense-in-depth (explicit blocklist + allowlist
  fallback)
- **Streaming downloads** with size limits prevent memory exhaustion
- **Audit logging** provides a forensic trail with consistent timestamps
- **Thread-safe rate limiting** prevents concurrent abuse
- **.gitignore** correctly excludes `.env` and `.google_cookies.json`
- **No hardcoded secrets** anywhere in the codebase
