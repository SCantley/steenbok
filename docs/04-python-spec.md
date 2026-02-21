# Python Specification: `searcher` Library & CLI

**Project:** Brave Search API Replacement  
**Date:** 2026-02-17  
**Implementation:** Steve (Cursor)  
**Language:** Python 3.11+

---

## 1. Overview

`searcher` is a Python library and CLI tool that provides web search via a chain of backends:

1. **SearXNG** (primary — self-hosted, free, unlimited)
2. **Google Custom Search API** (fallback — official, 100/day free)
3. *(Optional)* **DuckDuckGo** (emergency fallback — fragile, rate-limited, use sparingly)

It is designed to be a drop-in replacement for the Brave Search API calls in OpenClaw.

---

## 2. Package Structure

```
searcher/
├── __init__.py          # Public API exports
├── models.py            # Pydantic/dataclass models (SearchResult, SearchResponse)
├── backends/
│   ├── __init__.py
│   ├── base.py          # Abstract base class for backends
│   ├── searxng.py       # SearXNG backend
│   ├── google_cse.py    # Google Custom Search backend
│   └── duckduckgo.py    # DDG fallback backend (optional)
├── cache.py             # SQLite result cache
├── rate_limiter.py      # Token bucket rate limiter
├── chain.py             # Backend chain / fallback logic
├── config.py            # Configuration (env vars, defaults)
├── cli.py               # Click-based CLI entry point
└── exceptions.py        # Custom exceptions

tests/
├── test_models.py
├── test_cache.py
├── test_rate_limiter.py
├── test_searxng.py      # With httpx mock
├── test_google_cse.py   # With httpx mock
└── test_chain.py        # Integration tests

pyproject.toml
README.md
docker-compose.yml       # SearXNG setup
searxng-config/
└── settings.yml         # SearXNG configuration
```

---

## 3. Data Models

### 3.1 SearchResult

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    published_date: Optional[str] = None   # ISO 8601 or None
    source_engine: Optional[str] = None    # e.g. "google", "bing" (from SearXNG)
    rank: int = 0                           # 1-based position in results

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "published_date": self.published_date,
            "source_engine": self.source_engine,
            "rank": self.rank,
        }
```

### 3.2 SearchResponse

```python
@dataclass
class SearchResponse:
    query: str
    backend: str                        # Which backend served this response
    results: list[SearchResult]
    total_results: Optional[int] = None # Estimated total (not always available)
    elapsed_ms: int = 0
    cached: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "backend": self.backend,
            "results": [r.to_dict() for r in self.results],
            "total_results": self.total_results,
            "elapsed_ms": self.elapsed_ms,
            "cached": self.cached,
        }
```

### 3.3 SearchOptions

```python
from enum import Enum
from dataclasses import dataclass, field

class TimeRange(str, Enum):
    DAY = "day"
    WEEK = "week"       # Maps to "month" in SearXNG (no "week" there; use "month" approx)
    MONTH = "month"
    YEAR = "year"

class SafeSearch(int, Enum):
    OFF = 0
    MODERATE = 1
    STRICT = 2

@dataclass
class SearchOptions:
    num_results: int = 10               # 1–20
    time_range: Optional[TimeRange] = None
    safe_search: SafeSearch = SafeSearch.MODERATE
    language: str = "en"
    region: str = "en-US"
    categories: list[str] = field(default_factory=lambda: ["general"])
    page: int = 1                       # Pagination (1-indexed)
```

---

## 4. Backend Interface

### 4.1 Abstract Base Class

```python
from abc import ABC, abstractmethod

class SearchBackend(ABC):
    name: str = "base"
    
    @abstractmethod
    async def search(
        self, 
        query: str, 
        options: SearchOptions
    ) -> SearchResponse:
        """
        Perform a search. 
        Raises: BackendError on failure, RateLimitError if rate-limited.
        """
        ...
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if backend is reachable and functioning."""
        ...
    
    def is_available(self) -> bool:
        """Return False if backend is in circuit-breaker cooldown."""
        ...
```

### 4.2 SearXNG Backend

**File:** `backends/searxng.py`

**Config (from env or config):**
```python
SEARXNG_BASE_URL: str = "http://localhost:8888"  # env: SEARXNG_URL
SEARXNG_TIMEOUT: float = 10.0                    # env: SEARXNG_TIMEOUT
SEARXNG_MAX_RESULTS: int = 20
```

**Implementation notes:**
- Use `httpx.AsyncClient` for async HTTP
- Set a descriptive User-Agent: `searcher/1.0 (self-hosted; https://github.com/yourrepo)`
- Request URL: `{base_url}/search?q={query}&format=json&...`
- Map `SearchOptions` to SearXNG params:
  - `num_results` → `pageno` controls which page; SearXNG returns ~10 results/page by default
  - `time_range` → `time_range` (day/month/year; no "week" — use "month" for "week")
  - `safe_search` → `safesearch` (0/1/2)
  - `language` → `language` 
  - `categories` → `categories`
  - `page` → `pageno`
- Parse response `results` array into `SearchResult` objects
- Handle: `content` field → `snippet`, `url`, `title`, `publishedDate` → `published_date`, `engine` → `source_engine`
- Raise `BackendUnavailableError` if connection refused (container not running)
- Raise `BackendError` on 4xx/5xx
- Raise `RateLimitError` on 429

**SearXNG response fields:**
```
results[].url           → SearchResult.url
results[].title         → SearchResult.title
results[].content       → SearchResult.snippet
results[].publishedDate → SearchResult.published_date (may be None)
results[].engine        → SearchResult.source_engine (primary engine)
results[].engines       → list of all engines that returned this result
results[].score         → optional float (not exposed in our model)
```

**Health check:** `GET {base_url}/` — success if 200, even if HTML.

### 4.3 Google Custom Search Backend

**File:** `backends/google_cse.py`

**Config (from env):**
```python
GOOGLE_CSE_API_KEY: str   # env: GOOGLE_CSE_API_KEY (required)
GOOGLE_CSE_ID: str        # env: GOOGLE_CSE_ID (required)
GOOGLE_CSE_TIMEOUT: float = 10.0
GOOGLE_CSE_MAX_RESULTS: int = 10  # API max per request is 10
```

**Request:**
```
GET https://customsearch.googleapis.com/customsearch/v1
  ?key={api_key}
  &cx={cse_id}
  &q={query}
  &num={min(num_results, 10)}
  &lr=lang_{language}
  &dateRestrict={date_restrict}   # d1, w1, m1, m12 for day/week/month/year
  &safe={safe}                     # off / medium / high
  &start={((page-1)*10)+1}
```

**Date restrict mapping:**
```python
TIME_RANGE_MAP = {
    TimeRange.DAY: "d1",
    TimeRange.WEEK: "w1",
    TimeRange.MONTH: "m1",
    TimeRange.YEAR: "m12",
}
```

**Response parsing:**
```
items[].title         → SearchResult.title
items[].link          → SearchResult.url
items[].snippet       → SearchResult.snippet
items[].pagemap.metatags[0].date → SearchResult.published_date (best effort)
searchInformation.totalResults → SearchResponse.total_results
```

**Quota handling:**
- Track daily usage in cache/SQLite: increment a counter keyed on today's date
- If daily count ≥ 95 (leave 5 buffer), raise `QuotaExhaustedError`
- This prevents surprise charges

**Health check:** Make a test query for "test" with num=1. Return True if 200.
Note: This uses quota. Only call health_check when the backend is newly activated.

**Rate limiting:** Max 10 requests/minute to stay safe with free tier. The 100/day limit
is the real constraint, not requests/minute, but being polite helps avoid quota errors.

### 4.4 DuckDuckGo Backend (Optional / Emergency)

**File:** `backends/duckduckgo.py`

**Implementation:**
- Use `duckduckgo_search` library: `pip install duckduckgo-search`
- Wrap `DDGS().text()` in an async executor (`loop.run_in_executor`) since the lib is sync
- Catch `RatelimitException` → raise `RateLimitError`
- This backend should only be used as a last resort

**Config:**
```python
DDG_ENABLED: bool = False  # env: DDG_ENABLED (must explicitly opt in)
```

**Note:** This backend should be documented as "use at your own risk."

---

## 5. Cache Layer

**File:** `cache.py`

**Backend:** SQLite via Python stdlib `sqlite3`

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS search_cache (
    cache_key TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,     -- Unix timestamp
    expires_at INTEGER NOT NULL,     -- Unix timestamp
    hit_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quota_tracking (
    backend TEXT NOT NULL,
    date TEXT NOT NULL,              -- YYYY-MM-DD
    count INTEGER DEFAULT 0,
    PRIMARY KEY (backend, date)
);
```

**Cache key:** `sha256(f"{query}|{backend}|{options_canonical_json}")`

**TTL:** Configurable per backend:
- SearXNG default: 3600 seconds (1 hour)
- Google CSE default: 7200 seconds (2 hours, conserve quota)
- `time_range=day` queries: 900 seconds (15 min — fresher results needed)

**Interface:**
```python
class SearchCache:
    def __init__(self, db_path: str = "~/.searcher/cache.db"):
        ...
    
    def get(self, key: str) -> Optional[SearchResponse]:
        """Return cached response if exists and not expired."""
        ...
    
    def set(self, key: str, response: SearchResponse, ttl: int) -> None:
        """Store response in cache."""
        ...
    
    def increment_quota(self, backend: str, date: str) -> int:
        """Increment daily query count. Returns new count."""
        ...
    
    def get_quota(self, backend: str, date: str) -> int:
        """Get current daily query count for backend."""
        ...
    
    def evict_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        ...
```

**Cache location:** `~/.searcher/cache.db` (configurable via `SEARCHER_CACHE_PATH` env)

---

## 6. Rate Limiter

**File:** `rate_limiter.py`

**Algorithm:** Token bucket

```python
class TokenBucket:
    """Thread-safe token bucket rate limiter."""
    
    def __init__(self, rate: float, capacity: float):
        """
        rate: tokens per second to refill
        capacity: maximum tokens (burst ceiling)
        """
        ...
    
    async def acquire(self, tokens: float = 1.0) -> None:
        """Wait until a token is available, then consume it."""
        ...
    
    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Non-blocking acquire. Returns False if not enough tokens."""
        ...
```

**Per-backend limits:**
```python
RATE_LIMITS = {
    "searxng": TokenBucket(rate=1.0, capacity=5),      # 1/sec, burst 5
    "google_cse": TokenBucket(rate=0.17, capacity=2),  # 10/min = 0.17/sec
    "duckduckgo": TokenBucket(rate=0.1, capacity=1),   # 6/min, very conservative
}
```

---

## 7. Backend Chain

**File:** `chain.py`

**Class:** `SearchChain`

```python
class SearchChain:
    def __init__(
        self,
        backends: list[SearchBackend],
        cache: SearchCache,
        rate_limits: dict[str, TokenBucket],
    ):
        ...
    
    async def search(
        self,
        query: str,
        options: Optional[SearchOptions] = None,
        skip_cache: bool = False,
    ) -> SearchResponse:
        """
        Search with automatic fallback.
        
        Flow:
        1. Check cache. If hit, return immediately.
        2. For each backend in order:
           a. Check if backend is available (not in circuit breaker cooldown)
           b. Acquire rate limit token (await)
           c. Call backend.search()
           d. On success: cache result, return
           e. On RateLimitError: wait backoff, try next backend
           f. On BackendError: log warning, try next backend
           g. On BackendUnavailableError: log error, try next backend
        3. If all backends fail: raise AllBackendsFailedError
        """
        ...
```

**Circuit Breaker:**
```python
@dataclass
class CircuitBreaker:
    failure_threshold: int = 5          # Mark unavailable after N consecutive failures
    cooldown_seconds: int = 300         # 5 minutes before retrying
    failure_count: int = 0
    last_failure_time: Optional[float] = None
    
    def record_failure(self) -> None: ...
    def record_success(self) -> None: ...
    def is_open(self) -> bool: ...      # True = backend is unavailable
```

---

## 8. Configuration

**File:** `config.py`

All configuration via environment variables with sensible defaults:

```python
@dataclass
class Config:
    # SearXNG
    searxng_url: str = "http://localhost:8888"
    searxng_timeout: float = 10.0
    searxng_enabled: bool = True
    
    # Google CSE
    google_cse_api_key: str = ""        # Required for Google fallback
    google_cse_id: str = ""             # Required for Google fallback
    google_cse_enabled: bool = True     # Auto-disabled if keys not set
    google_cse_daily_limit: int = 95    # Hard stop before hitting 100/day cap
    
    # DuckDuckGo
    ddg_enabled: bool = False           # Must explicitly opt in
    
    # Cache
    cache_path: str = "~/.searcher/cache.db"
    cache_ttl_default: int = 3600       # 1 hour
    cache_ttl_fresh: int = 900          # 15 min for time-ranged queries
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "json"            # "json" or "text"
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load config from environment variables."""
        ...
```

**Environment variable naming:** `SEARCHER_<FIELD_UPPER>`, e.g.:
- `SEARCHER_SEARXNG_URL`
- `SEARCHER_GOOGLE_CSE_API_KEY`
- `SEARCHER_CACHE_PATH`
- `SEARCHER_LOG_LEVEL`

**Config file fallback:** If `~/.searcher/config.toml` exists, load it before env vars.
Env vars override config file values.

---

## 9. Public API

**File:** `__init__.py`

```python
from searcher import search, SearchOptions, TimeRange, SafeSearch

# Simple synchronous wrapper (for CLI and non-async callers)
def search(
    query: str,
    *,
    num_results: int = 10,
    time_range: Optional[str] = None,  # "day", "week", "month", "year"
    safe_search: str = "moderate",
    language: str = "en",
    page: int = 1,
    skip_cache: bool = False,
    backend: Optional[str] = None,     # Force specific backend: "searxng", "google"
) -> SearchResponse:
    """
    Synchronous search. Runs event loop internally.
    For async callers, use `async_search()` instead.
    """
    ...

async def async_search(query: str, **kwargs) -> SearchResponse:
    """Async version. Use in async contexts."""
    ...
```

**Usage example (sync):**
```python
from searcher import search

results = search("python asyncio best practices", num_results=5)
for r in results.results:
    print(f"{r.rank}. {r.title}")
    print(f"   {r.url}")
    print(f"   {r.snippet[:100]}...")
```

**Usage example (async):**
```python
from searcher import async_search, SearchOptions, TimeRange

options = SearchOptions(num_results=10, time_range=TimeRange.WEEK)
response = await async_search("AI news", options=options)
```

---

## 10. CLI

**File:** `cli.py`  
**Framework:** `click` (or stdlib `argparse` to minimize deps)

**Entry point** (in `pyproject.toml`):
```toml
[project.scripts]
searcher = "searcher.cli:main"
```

**Commands:**

### `searcher search`

```
searcher search [OPTIONS] QUERY

Options:
  -n, --num INTEGER          Number of results [default: 10]
  -t, --time-range TEXT      Time filter: day, week, month, year
  -b, --backend TEXT         Force backend: searxng, google, duckduckgo
  --no-cache                 Skip cache
  --json                     Output as JSON (default: human-readable)
  -v, --verbose              Show backend, timing, cache info
  --help                     Show this message
```

**Human-readable output:**
```
Search: "python asyncio" (via searxng, 342ms, cached: no)
─────────────────────────────────────────────────────
 1. Python asyncio — official docs
    https://docs.python.org/3/library/asyncio.html
    Asyncio is a library to write concurrent code using the async/await syntax...

 2. Real Python: Async IO in Python
    https://realpython.com/async-io-python/
    ...
```

**JSON output:**
```json
{
  "query": "python asyncio",
  "backend": "searxng",
  "elapsed_ms": 342,
  "cached": false,
  "total_results": 1500000,
  "results": [
    {
      "rank": 1,
      "title": "Python asyncio — official docs",
      "url": "https://docs.python.org/3/library/asyncio.html",
      "snippet": "...",
      "published_date": null,
      "source_engine": "google"
    }
  ]
}
```

### `searcher status`

```
searcher status

Checks connectivity to all configured backends:

Backends:
  ✅ searxng      http://localhost:8888  (healthy, 45ms)
  ✅ google_cse   quota: 12/95 today
  ❌ duckduckgo   disabled

Cache:
  Path: /Users/steve/.searcher/cache.db
  Entries: 847 (23 expired)
  Size: 2.1 MB
```

### `searcher cache clear`

```
searcher cache clear [--expired-only]
```

### `searcher setup`

```
searcher setup

Interactive wizard:
  1. Check Docker + SearXNG
  2. Prompt for Google CSE credentials
  3. Write ~/.searcher/config.toml
  4. Run health checks
```

---

## 11. Error Handling

### Exception Hierarchy

```python
class SearcherError(Exception): ...

class BackendError(SearcherError):
    def __init__(self, backend: str, message: str, status_code: int = None): ...

class BackendUnavailableError(BackendError): ...   # Connection refused / DNS fail
class RateLimitError(BackendError): ...             # 429 or explicit rate limit
class QuotaExhaustedError(BackendError): ...        # Daily quota hit (Google CSE)
class AllBackendsFailedError(SearcherError): ...    # Every backend in chain failed
class ConfigurationError(SearcherError): ...        # Missing required config
```

### Error Behavior

| Condition | Behavior |
|-----------|----------|
| SearXNG connection refused | Log WARNING, try next backend |
| SearXNG 429 | Log WARNING, record circuit breaker failure, try next |
| SearXNG 500 | Log WARNING, retry once after 2s, then try next |
| Google CSE quota at 95/day | Log WARNING, skip Google, try next |
| Google CSE 403 (bad key) | Log ERROR, disable backend, raise ConfigurationError |
| All backends failed | Raise AllBackendsFailedError with list of errors |
| Network timeout (10s) | Log WARNING, try next backend |

### Retry Strategy

```python
RETRY_CONFIG = {
    "max_attempts": 2,
    "initial_wait": 2.0,    # seconds
    "backoff_factor": 2.0,  # exponential: 2s, 4s
    "retryable_status": {500, 502, 503, 504},
    "not_retryable": {400, 401, 403, 404, 429},
}
```

---

## 12. Logging

Use Python `logging` module. Structured JSON format via `python-json-logger` (optional dep).

**Log events:**
```python
# At INFO level:
logger.info("search.request", extra={
    "query": query, "backend": backend.name, "options": options.to_dict()
})
logger.info("search.response", extra={
    "query": query, "backend": backend.name, "elapsed_ms": elapsed,
    "num_results": len(results), "cached": cached
})

# At WARNING level:
logger.warning("backend.error", extra={
    "backend": backend.name, "error": str(e), "status_code": e.status_code
})
logger.warning("backend.fallback", extra={
    "failed": failed_backend, "using": next_backend
})

# At ERROR level:
logger.error("all_backends_failed", extra={"query": query, "errors": error_list})
```

---

## 13. Dependencies

**Core (required):**
```toml
[project.dependencies]
httpx = ">=0.27"          # Async HTTP client
click = ">=8.0"           # CLI framework
```

**Optional extras:**
```toml
[project.optional-dependencies]
json-logging = ["python-json-logger>=2.0"]
duckduckgo = ["duckduckgo-search>=7.0"]
dev = ["pytest", "pytest-asyncio", "respx", "mypy", "ruff"]
```

**Zero-dependency core option:** If you want to minimize deps, replace `httpx` with
`urllib.request` (stdlib). Acceptable for this use case since we control the runtime.
`click` can also be replaced with `argparse`. Noted here as an alternative.

---

## 14. Testing Strategy

### Unit Tests

- `test_models.py`: Serialize/deserialize SearchResult, SearchResponse
- `test_cache.py`: Get/set/expire, quota tracking, eviction
- `test_rate_limiter.py`: Token refill, blocking, non-blocking acquire
- `test_searxng.py`: Mock httpx responses for success, 429, 500, connection error
- `test_google_cse.py`: Mock httpx, test quota tracking, date restrict mapping
- `test_chain.py`: Fallback logic, circuit breaker, all-backends-fail

### Integration Tests

```bash
# Requires running SearXNG:
pytest tests/ -m integration

# Tests against live SearXNG (not mocked)
# Asserts: response in <5s, ≥3 results, valid URLs
```

### Example Mock (using `respx`):

```python
import respx
import httpx
import pytest

@pytest.mark.asyncio
async def test_searxng_success():
    with respx.mock:
        respx.get("http://localhost:8888/search").mock(
            return_value=httpx.Response(200, json={
                "query": "python",
                "results": [
                    {"title": "Python", "url": "https://python.org", 
                     "content": "Programming language", "engine": "google"}
                ]
            })
        )
        backend = SearXNGBackend(base_url="http://localhost:8888")
        response = await backend.search("python", SearchOptions())
        assert len(response.results) == 1
        assert response.results[0].url == "https://python.org"
```

---

## 15. Installation & Setup

```bash
# Clone or copy the searcher package
cd ~/projects/searcher

# Install in development mode
pip install -e ".[dev]"

# Set up SearXNG
docker compose up -d

# Configure Google CSE (optional but recommended)
export SEARCHER_GOOGLE_CSE_API_KEY="your-key"
export SEARCHER_GOOGLE_CSE_ID="your-cse-id"

# Or run interactive setup wizard
searcher setup

# Test it
searcher status
searcher search "python asyncio" -n 5 --json
```

---

## 16. OpenClaw Integration Notes

To replace the current Brave `web_search` tool in OpenClaw:

**Option A: Replace the web_search tool implementation**
- The `web_search` tool in OpenClaw calls Brave's API
- Replace the underlying HTTP call with `searcher.async_search()`
- This is the cleanest integration

**Option B: Drop-in via env**
- If OpenClaw's `web_search` is configurable, point it at SearXNG directly
  (some agents support `SEARXNG_URL` env var out of the box)
- Check OpenClaw config for search provider settings

**Option C: Subprocess from tools**
- For quick integration: call `searcher search "{query}" --json` as a subprocess
- Parse stdout JSON in the calling code
- Not ideal but works as a bridge while integrating properly

**Recommended:** Option A. The `async_search()` function is designed to slot in
where `httpx.get(brave_url, ...)` currently lives.

---

## 17. SearXNG Settings Template

**File:** `searxng-config/settings.yml`

Key settings to include in the config volume:

```yaml
use_default_settings: true

general:
  debug: false
  instance_name: "local-searxng"
  
search:
  safe_search: 0
  autocomplete: ""
  default_lang: "en"
  formats:
    - html
    - json          # ← Critical: must enable JSON format
  
server:
  port: 8080
  bind_address: "127.0.0.1"
  secret_key: "generate-a-random-32-char-string-here"
  
# Tune engines for local use (reduce noise, improve speed)
engines:
  - name: google
    engine: google
    shortcut: g
    timeout: 3.0
    
  - name: bing
    engine: bing
    shortcut: b
    timeout: 3.0

  - name: duckduckgo
    engine: duckduckgo
    shortcut: d
    timeout: 3.0
    
  - name: startpage
    engine: startpage
    shortcut: sp
    timeout: 5.0
```

---

## 18. Milestone Checklist (for Steve)

- [ ] Docker Desktop installed and running
- [ ] `docker-compose.yml` and `settings.yml` created (templates above)
- [ ] `docker compose up -d` — SearXNG running at http://localhost:8888
- [ ] Verify: `curl "http://localhost:8888/search?q=test&format=json"` returns JSON
- [ ] Google CSE set up (programmablesearchengine.google.com)
- [ ] API key created in Google Cloud Console
- [ ] `pip install -e ".[dev]"` in searcher project
- [ ] `searcher status` shows all backends healthy
- [ ] `searcher search "test query" --json` returns results
- [ ] Integration into OpenClaw `web_search` tool
- [ ] Brave API key removed from env
