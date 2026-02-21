---
name: Security Assessment Remediation
overview: Implement all eight security fixes from the assessment document, plus enhanced audit logging that captures allowlist violations and all failed queries.
todos: []
---

# Security Assessment Remediation Plan

Implement corrections from [project/plans/security-assessment-v1.md](project/plans/security-assessment-v1.md), plus audit logging for allowlist violations and failed queries.

---

## Summary of Changes

| Risk | Severity | File(s)      | Approach                                         |
| ---- | -------- | ------------- | ------------------------------------------------ |
| 1    | 5/5      | fetch.py      | Manual redirect handling with per-hop validation |
| 2    | 4/5      | fetch.py      | Use `ipaddress` module for IP checks             |
| 3    | 3/5      | allowlist.py  | Document trade-off (Option A)                    |
| 4    | 2/5      | fetch.py      | Streaming with chunked read                      |
| 5    | 2/5      | fetch.py      | Content-Type validation (allowlist + blocklist)  |
| 6    | 2/5      | fetch.py      | Thread-safe rate limiter                         |
| 7    | 1/5      | fetch.py      | Structured audit logging                         |
| 8    | 1/5      | cli.py        | Remove double unquote                            |

---

## Risk 1: SSRF via Redirect Chain

**Problem:** `follow_redirects=True` lets httpx follow up to 3 redirects without re-checking the destination against the allowlist.

**Solution:** Disable automatic redirects; handle them manually:

1. Set `follow_redirects=False` on the httpx client
2. On 3xx responses, extract `Location` header and validate the absolute URL
3. Resolve the redirect target host to an IP and run it through the same private IP blocklist (Risk 2 fix)
4. Re-check `allowlist.is_allowed()` on the redirect URL
5. Loop manually (up to `MAX_REDIRECTS` times) until a non-redirect response or rejection

**Location:** [src/fetch.py](src/fetch.py) lines 140-151 — replace the `client.get()` block with a manual redirect loop.

---

## Risk 2: Incomplete Private IP Blocking

**Problem:** Regex misses `0.0.0.0`, `169.254.x.x`, IPv6 (`fc00::/7`, `fe80::/10`), IPv4-mapped IPv6, bracketed IPv6.

**Solution:** Use the `ipaddress` module. See original plan for details.

**Location:** [src/fetch.py](src/fetch.py) lines 30-33, 62-66.

---

## Risk 3: Overly Broad Wildcards — Option A (Confirmed)

**Solution:** Document only. Add a brief note in docstrings and/or module docstring that `*.edu` and `*.ac.uk` are broad by design and represent a known trade-off (many institutions, some risk from compromised subdomains).

**Location:** [src/allowlist.py](src/allowlist.py) — docstring for `DEFAULT_ALLOWED` or module.

---

## Risk 4: Full Download Before Size Check

**Solution:** Use streaming with chunked read. See original plan.

**Location:** [src/fetch.py](src/fetch.py) lines 152-156.

---

## Risk 5: Content-Type Validation — Formats to Consider

**Approach:** Use an **allowlist** for what we accept (`text/html`, `text/plain`, optionally `application/xhtml+xml`) plus an explicit **blocklist** for high-risk formats.

### Binary formats to block (payload / parser risk)

| Format              | Content-Type (examples)                                                                 | Why block |
|---------------------|-----------------------------------------------------------------------------------------|-----------|
| **Microsoft Office**| `application/msword`, `application/vnd.ms-excel`, `application/vnd.ms-powerpoint`, `application/vnd.openxmlformats-officedocument.*`, `application/vnd.ms-word.document.macroEnabled.*`, `application/vnd.ms-excel.sheet.macroEnabled.*`, `application/vnd.ms-powerpoint.presentation.macroEnabled.*` | Macros, OLE, RTF exploits, external payload loading |
| **RTF**             | `application/rtf`                                                                      | Can load external content; has had exploits        |
| **Archives**        | `application/zip`, `application/x-rar`, `application/x-7z-compressed`                   | Can contain executables; malware delivery          |
| **SVG**             | `image/svg+xml`                                                                        | Can embed scripts                                  |
| **Executables**     | `application/x-msdownload`, `application/x-executable`, `application/octet-stream`     | Obvious risk                                       |
| **JavaScript**      | `application/javascript`                                                               | Not HTML; trafilatura expects markup               |

### Formats that are “safe” but not useful

| Format    | Content-Type   | Note |
|-----------|----------------|------|
| **PDF**   | `application/pdf` | No macro/script risk; trafilatura can’t parse it anyway — would produce garbage. Reject for consistency. |
| **Images**| `image/png`, `image/jpeg`, etc. | No code execution; trafilatura would produce garbage. Reject. |
| **JSON**  | `application/json` | Safe but not HTML. Reject. |

### Recommended implementation

1. **Allowlist:** Proceed only if `Content-Type` contains (case-insensitive) `text/html`, `text/plain`, or `application/xhtml+xml`.
2. **Explicit blocklist:** Before the allowlist check, reject if Content-Type contains any of:
   - `application/msword`
   - `application/vnd.ms-` (covers Word, Excel, PowerPoint, macro-enabled, etc.)
   - `application/vnd.openxmlformats-officedocument` (Office OOXML)
   - `application/rtf`
   - `application/zip`, `application/x-rar`, `application/x-7z`
   - `image/svg+xml`
   - `application/javascript`
   - `application/x-msdownload`

3. **Everything else:** Reject with a generic “Unsupported content type” message.

This keeps MS Office and other high-risk formats blocked even if a server sends a wrong or unusual Content-Type, while remaining clear about what is allowed.

**Location:** [src/fetch.py](src/fetch.py), in the fetch logic before decoding content.

---

## Risk 6: Rate Limiter Not Thread-Safe

**Is the code threaded?** Today: Flask’s dev server is single-threaded. But if you deploy with gunicorn, uwsgi, or another production WSGI server, it is typically multi-threaded or multi-worker. The bug is latent — it would only surface in that setup. Fixing it now is low cost and avoids future breakage.

**Solution:** Use `threading.Lock()`:

1. Add `_rate_limit_lock = threading.Lock()` at module level
2. Wrap the rate-limit logic in `with _rate_limit_lock:` so only one thread updates/waits at a time

**Location:** [src/fetch.py](src/fetch.py) lines 89-102.

---

## Risk 7: Audit Logging — Consistent Timestamp

**Requirement:** Log allowlist violations, all failed queries, and successful fetches. **All log entries use the same date/time format** (e.g. ISO 8601: `2026-02-20T14:30:00.123Z` or `%Y-%m-%dT%H:%M:%S.%fZ`).

**Solution:**

1. Configure the `steenbok.fetch` logger with a formatter that outputs timestamps in that format on every line.
2. Centralize logging in `fetch()`:
   - Allowlist rejection: `reason="allowlist_violation"`, url, timestamp
   - URL blocked: `reason="url_blocked"`, url, timestamp
   - HTTP/request/extraction failure: `reason="fetch_failed"`, url, error, timestamp
   - Success: `reason="success"`, url, status_code, bytes, elapsed, timestamp

3. Use structured fields (e.g. `extra` dict) so logs are parseable. The formatter ensures all entries share the same timestamp format.

**Location:** [src/fetch.py](src/fetch.py) — add logging; configure formatter for consistent `datetime` output.

---

## Risk 8: Double URL-Decoding

**Solution:** Remove `unquote()` on line 75. Use `url_param` directly. Remove unused `unquote` import.

**Location:** [src/cli.py](src/cli.py) line 75.

---

## Implementation Order

1. Risk 2 (IP blocking)
2. Risk 1 (SSRF redirect)
3. Risk 6 (rate limiter)
4. Risk 8 (unquote)
5. Risk 5 (Content-Type)
6. Risk 4 (streaming)
7. Risk 7 (logging)
8. Risk 3 (documentation)

---

## Testing

- IP blocking: 169.254.x.x, 0.0.0.0, IPv6 cases
- Redirect validation: allowlisted → non-allowlisted fails
- Content-Type: allow text/html, text/plain; reject MS Office, PDF, ZIP, etc.
- Streaming size limit with mocked large response
- Thread-safe rate limiter (concurrent requests)
- Logging (e.g. pytest `caplog`)
- Remove unquote: verify Flask endpoint behavior
