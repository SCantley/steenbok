# Security Assessment v3: Steenbok Safe Fetch

**Date:** 2026-02-20
**Scope:** `src/fetch.py`, `src/cli.py`, `src/allowlist.py`, `requirements.txt`, `.gitignore`
**Assessor:** Automated review (Claude)
**Prior assessment:** `project/security-assessment-v2.md` (9 risks; 7 remediated, 1 accepted, 1 partially mitigated)

---

## Executive Summary

The v2 assessment identified 9 risks on a 1-10 severity scale. Since that assessment, the
codebase has been substantially hardened:

- **DNS rebinding on initial fetch** (v2 severity 7) -- remediated via
  `_resolve_and_validate_host()` before the first HTTP request
- **Overly permissive Google wildcards** (v2 severity 6) -- remediated; narrowed to
  `www.google.com`, `scholar.google.com`, `books.google.com`, `patents.google.com`
- **Unused browser-cookie3 dependency** (v2 severity 5) -- remediated; removed from
  `requirements.txt`
- **No HTTPS enforcement** (v2 severity 4) -- remediated; HTTPS-only by default, HTTP
  opt-in via `STEENBOK_ALLOW_HTTP=1`
- **Unpinned dependency versions** (v2 severity 4) -- remediated; all dependencies pinned
  with `==`
- **Error message information leakage** (v2 severity 2) -- remediated; Flask endpoint now
  returns generic messages
- **Rate limiter holds lock during sleep** (v2 severity 2) -- remediated; lock released
  before `time.sleep()`

This v3 assessment identifies **5 remaining or new risks** on a 1-5 severity scale. The
highest-rated item is 3/5. The codebase is in strong security posture for its intended use
as a single-user, localhost-only research tool.

---

## Risk 1: Untrusted PDF Parsing Without Process Isolation -- Severity: 3/5

**What:** `_extract_text_pdf()` passes attacker-controlled bytes directly to PyMuPDF's
`fitz.open()` within the same Python process. PDF parsers are historically a rich source
of memory corruption vulnerabilities (CVEs in MuPDF, Poppler, etc.). A crafted PDF served
from an allowlisted domain could trigger a parser bug leading to a crash or, in the worst
case, code execution.

Python's `try/except Exception` wrapper (fetch.py line 212) does not catch memory
corruption -- those bypass the exception machinery entirely.

**Current mitigations:**
- 2 MB size cap (`MAX_PDF_BYTES`) applied before parsing
- PyMuPDF pinned to exact version (1.26.5)
- Only PDFs from allowlisted domains are fetched

**Location:** `src/fetch.py` lines 198-213

**Remediation:**
- **Minimum:** Keep PyMuPDF updated when new patch versions are released. Subscribe to
  MuPDF security advisories.
- **Ideal:** Run PDF parsing in a subprocess with resource limits (memory cap, wall-clock
  timeout, no network access). This isolates the main process from parser crashes. Medium
  implementation effort.

---

## Risk 2: Broad Wildcards (`*.edu`, `*.ac.uk`) -- Severity: 2/5

**What:** The default allowlist includes `*.edu` and `*.ac.uk`, which match tens of
thousands of subdomains. Any compromised or attacker-controlled page under these TLDs
(e.g., a student project on `users.cs.someuniversity.edu`) would be trusted by the fetch
pipeline. An agent consuming this output would treat the content as authoritative research
material.

**Current mitigations:**
- Documented as a known trade-off in `src/allowlist.py` comments (lines 14-16)
- User can narrow the allowlist via `~/.steenbok/allowlist.txt` or `STEENBOK_ALLOWED_DOMAINS`
- Content is text-extracted only (no script execution)

**Location:** `src/allowlist.py` lines 23-24

**Remediation:** Accepted for now. The breadth is deliberate to maximize research
coverage. If the tool's use case narrows to specific institutions, replace the wildcards
with explicit domains. No code change recommended at this time.

---

## Risk 3: TOCTOU Gap in DNS Validation -- Severity: 2/5

**What:** The `fetch()` function validates DNS resolution at line 304, then makes the HTTP
request at line 309. Between these two calls, `httpx` performs its own independent DNS
resolution. If an attacker controls DNS for an allowlisted domain (feasible under `*.edu`),
they could:

1. Return a safe public IP during `_resolve_and_validate_host()` (step 1)
2. Switch DNS to `169.254.169.254` or `127.0.0.1` before `httpx` connects (step 2)

The `_rate_limit()` call between validation and connection adds up to 5 seconds of delay,
widening the race window.

**Why this is hard to fix:** The proper mitigation is to connect to the resolved IP
directly and set the `Host` header / TLS SNI manually. This is complex with `httpx` and
breaks standard TLS certificate validation unless SNI is configured correctly. This is a
known limitation of application-layer SSRF protection across the industry.

**Current mitigations:**
- Attacker must control DNS for an allowlisted domain
- Very narrow timing requirement even with the 5-second window
- All SSRF-valuable targets (cloud metadata, localhost) are independently blocked by the
  IP blocklist on redirect hops

**Location:** `src/fetch.py` lines 301-314

**Remediation:** Accepted as a residual risk. The practical exploitability is low given the
constraints. If higher assurance is needed in the future, consider using `httpx`'s
transport layer to pin the resolved IP for the connection.

---

## Risk 4: Unused `requests` Dependency -- Severity: 1/5

**What:** `requests==2.32.5` is listed in `requirements.txt` but is not imported anywhere
in `src/`. The codebase uses `httpx` for all HTTP operations. An unused dependency
increases supply chain attack surface: if a compromised version of `requests` is published,
it would be installed into the Steenbok environment without being noticed, since nothing
calls it.

**Location:** `requirements.txt` line 1

**Remediation:** Remove `requests==2.32.5` from `requirements.txt`. If it is needed by a
future component, add it back when that component is implemented. Trivial one-line fix.

---

## Risk 5: Flask Endpoint Has No Authentication -- Severity: 1/5

**What:** The `/fetch` endpoint at `127.0.0.1:8877` accepts requests from any local
process without authentication. A rogue process on the same machine could call the endpoint
to fetch content from allowlisted domains.

**Mitigating factors:**
- Binds to `127.0.0.1` only (no remote access)
- All requests constrained by the domain allowlist
- Every request is audit-logged with timestamp, URL, and outcome
- Single-user deployment on personal equipment
- Attacker gains little: they can only fetch publicly accessible academic content

**Location:** `src/cli.py` lines 69-87

**Remediation:** Accepted as-is. If deployment context changes (shared machine,
network-exposed), revisit with a startup token or Unix domain socket.

---

## v2 Risk Remediation Status

| v2 # | Risk | v2 Severity | Current Status |
|-------|------|-------------|----------------|
| 1 | DNS rebinding on initial fetch | 7/10 | **Remediated** -- `_resolve_and_validate_host()` added before first HTTP request (fetch.py:301-304) |
| 2 | Overly permissive Google wildcards | 6/10 | **Remediated** -- narrowed to 4 specific subdomains (allowlist.py:28-31) |
| 3 | Untrusted PDF parsing (PyMuPDF) | 5/10 | **Partially mitigated** -- size limit + pinned version; no subprocess isolation (v3 Risk 1) |
| 4 | Unused browser-cookie3 dependency | 5/10 | **Remediated** -- removed from requirements.txt |
| 5 | No HTTPS enforcement | 4/10 | **Remediated** -- HTTPS-only default; HTTP opt-in via env var (fetch.py:125-126) |
| 6 | Unpinned dependency versions | 4/10 | **Remediated** -- all deps pinned with `==` (requirements.txt) |
| 7 | Flask endpoint no authentication | 1/10 | **Accepted** -- localhost + allowlist + audit logging (v3 Risk 5) |
| 8 | Error message information leakage | 2/10 | **Remediated** -- generic messages returned to HTTP clients (cli.py:78-84) |
| 9 | Rate limiter holds lock during sleep | 2/10 | **Remediated** -- lock released before sleep; retry loop re-acquires (fetch.py:182-195) |

---

## Positive Findings

The codebase demonstrates strong security practices:

- **SSRF protection** is layered: URL validation, allowlist, DNS resolution with IP
  blocklist, and per-hop redirect validation
- **IP blocking** uses the `ipaddress` module correctly, covering IPv4, IPv6,
  IPv4-mapped IPv6, loopback, link-local, private, reserved, and unspecified addresses
- **Content-Type validation** uses defense-in-depth (explicit blocklist for dangerous
  types + allowlist for processable types)
- **Streaming downloads** with size limits prevent memory exhaustion
- **Manual redirect handling** re-validates every hop against both the allowlist and
  IP blocklist
- **Audit logging** with ISO 8601 timestamps provides a forensic trail for every request
- **Thread-safe rate limiting** with lock-free sleep prevents both concurrent abuse and
  self-inflicted denial of service
- **HTTPS enforced by default** with explicit opt-in required for HTTP
- **All dependencies pinned** to exact versions
- **`.gitignore`** correctly excludes `.env` and `.google_cookies.json`
- **No hardcoded secrets** anywhere in the codebase
- **Generic error messages** returned to HTTP clients; detailed errors logged server-side

---

## Recommendations

**Trivial fix (Risk 4):**
Remove the unused `requests` dependency from `requirements.txt`. One line, no code changes.

**Ongoing maintenance (Risk 1):**
Keep PyMuPDF updated. When upgrading, check MuPDF release notes for security fixes. If
Steenbok's usage grows beyond personal research, invest in subprocess isolation for PDF
parsing.

**No action needed (Risks 2, 3, 5):**
These are accepted risks with appropriate mitigations for the current single-user,
localhost-only deployment model. Revisit if the deployment context changes.
