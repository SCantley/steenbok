# Requirements: Web Search Tool

**Project:** Brave Search API Replacement  
**Date:** 2026-02-17

---

## 1. Background & Problem Statement

OpenClaw currently uses the Brave Search API for programmatic web search.
Brave eliminated its free tier in February 2026; the replacement $5/month
credit gives ~1,000 queries before billing begins and requires public attribution.

We need a replacement that:
- Costs nothing (or near-nothing) to run
- Can be called programmatically from Python
- Will not get us banned or violate ToS
- Works at the scale we use (~60 searches/day, occasionally bursty)

---

## 2. Functional Requirements

### 2.1 Core Search Capability

| Requirement | Priority | Notes |
|-------------|----------|-------|
| Full web search (not just instant answers) | Must | Not DuckDuckGo Instant Answers API |
| Return URLs, titles, and text snippets | Must | Same shape as Brave response |
| Configurable result count (1–20) | Must | Default 10 |
| Search query string input | Must | Plain text, boolean operators if possible |
| Return structured data (dict/JSON), not HTML | Must | Machine-readable |

### 2.2 Filtering & Options

| Requirement | Priority | Notes |
|-------------|----------|-------|
| Time/freshness filter | Should | day / week / month / year |
| Safe search toggle | Should | on / off / moderate |
| Language/region filter | Should | en-US default |
| Category filter | Could | news, images, general |
| Page offset / pagination | Could | For deep result fetching |

### 2.3 Result Schema

Each result must provide (at minimum):

```python
{
    "title": str,          # Page title
    "url": str,            # Canonical URL
    "snippet": str,        # Text excerpt / description
    "published_date": str | None,  # ISO date if available
    "source": str,         # Which backend returned this
}
```

Nice-to-have:
- `rank`: integer position
- `score`: relevance score if available
- `favicon_url`: for UI display

### 2.4 Metadata Envelope

Results should be wrapped in a metadata envelope:

```python
{
    "query": str,
    "backend": str,
    "total_results": int | None,
    "elapsed_ms": int,
    "results": [...]
}
```

---

## 3. Non-Functional Requirements

### 3.1 Safety & Compliance

- **robots.txt**: Tool must not scrape sites that disallow bots via robots.txt.  
  (Self-hosted aggregators like SearXNG handle this upstream.)
- **Terms of Service**: Must not violate search engine ToS. Prefer engines that  
  explicitly permit programmatic access or offer an official API.
- **Rate limiting**: Must implement client-side rate limiting. No hammering upstream  
  services. Target ≤2 requests/second to any single upstream.
- **User-Agent**: When making HTTP requests, identify as the tool (not as a browser).

### 3.2 Reliability

- **Graceful fallback**: If primary backend fails, fall back to secondary.
- **Retries**: Retry transient errors (network timeout, 5xx) with exponential backoff.
- **Circuit breaker**: After N consecutive failures on a backend, mark it as  
  unavailable and skip to fallback for a cooldown period.
- **Timeouts**: All HTTP requests must time out (default: 10 seconds).

### 3.3 Performance

- **Response time**: ≤5 seconds for a standard 10-result query (P90).
- **Caching**: Cache results keyed on (query, options) for a configurable TTL  
  (default: 1 hour). Reduces redundant upstream calls.
- **Async**: Support asyncio for use in async contexts (OpenClaw integration).

### 3.4 Operability

- **Config via environment variables**: API keys, backend URLs, cache settings.
- **No secrets in code**: All credentials via env or config file.
- **Logging**: Structured logging (JSON) with DEBUG/INFO/WARNING/ERROR levels.
- **CLI usable**: Can be run from the command line for quick testing.
- **Library usable**: Importable Python module for agent integration.

### 3.5 Maintainability

- **Single-file core**: Main logic in one file where possible, avoid framework sprawl.
- **Typed**: Full type hints, mypy clean.
- **Minimal dependencies**: Core should run with stdlib + `httpx` (or `requests`).  
  Optional extras for caching, async, etc.
- **Tested**: Unit tests with mocked HTTP; integration test against live backends.

---

## 4. Scale Assumptions

| Metric | Current | Headroom |
|--------|---------|---------|
| Queries/day | ~60 | Plan for 200/day |
| Peak burst | ~5/min | Plan for 20/min |
| Query length | 5–15 words | Up to 200 chars |
| Results needed | 5–10 per query | Up to 20 |
| Concurrent callers | 1 (main session) | Up to 3 |

---

## 5. Out of Scope

- Image search (for now)
- Video search
- Knowledge graph / structured answers (Instant Answers style)
- Paying for search capacity — this project targets **zero ongoing cost**
- High-availability / redundant infrastructure (single Mac, single Docker container is fine)
- GDPR / privacy compliance (internal tool, Steve's data)
