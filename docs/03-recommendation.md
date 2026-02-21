# Recommendation: Approach & Rationale

**Project:** Brave Search API Replacement  
**Date:** 2026-02-17

---

## Recommended Architecture

```
┌─────────────────────────────────────────────┐
│              Python `searcher` tool          │
│                                             │
│  ┌─────────┐  fail   ┌──────────────────┐  │
│  │ SearXNG │ ──────► │ Google Custom    │  │
│  │(primary)│         │ Search (fallback) │  │
│  └─────────┘         └──────────────────┘  │
│       │                      │              │
│  ┌────▼──────────────────────▼──────┐      │
│  │         Result Cache (SQLite)    │      │
│  └───────────────────────────────────┘     │
└─────────────────────────────────────────────┘
         │
   ┌─────▼─────┐
   │  Docker   │
   │ SearXNG   │
   │ :8080     │
   └───────────┘
```

**Primary backend:** SearXNG running locally via Docker  
**Fallback backend:** Google Custom Search JSON API  
**Cache layer:** SQLite (file-based, zero extra dependencies)  
**Rate limiter:** Token bucket per backend, persisted in SQLite between runs

---

## Rationale

### Why SearXNG as Primary

1. **Zero cost, zero limits** — No API key, no account, no monthly quota.
   At 60 queries/day we are well below anything that would trigger upstream throttling.

2. **Aggregation = resilience** — SearXNG queries multiple engines simultaneously.
   If Google blocks it, Bing results still come through. If DuckDuckGo is slow, 
   Startpage fills in. Single-engine APIs are fragile; SearXNG is antifragile.

3. **Time filtering works** — `time_range=day|week|month|year` is natively supported.
   Critical for freshness-sensitive queries (news, recent events).

4. **Production-validated** — SearXNG is the search backend for LangChain, LiteLLM,
   Open WebUI, Perplexica, and many self-hosted AI stacks. It's battle-tested.

5. **Local privacy** — Queries never leave Steve's machine in a way tied to his identity.
   SearXNG instances don't log queries by default.

6. **Runs on your Mac** — Docker Desktop on Mac M-series works great. One `docker compose up -d`
   at startup (or via a launchd agent) and it's always available.

7. **JSON API is simple** — Single GET request, clean JSON response. Python wrapper is <200 lines.

### Why Google Custom Search as Fallback

1. **Official API** — Stable, documented, no ToS concerns. Google maintains it.

2. **100 free queries/day** — At our scale, this fallback will almost never be hit
   in normal operation. It's insurance for when SearXNG is down or rate-limited.

3. **High quality signal** — If SearXNG is struggling (engine blocks, timeouts),
   Google CSE will return reliable, high-quality results.

4. **Trivial setup** — One API key, one Search Engine ID. 10 minutes to configure.

### Why Not Others

- **DuckDuckGo lib**: Officially unsupported scraping. Frequently rate-limited in production.
  Multiple popular projects report instability. Not acceptable as a primary or reliable fallback.

- **Serper.dev / Tavily / Exa**: All require paying money. Our goal is zero ongoing cost.
  The 2,500 Serper.dev signup bonus could be registered as an emergency tertiary fallback,
  but shouldn't be counted on.

- **Brave (current)**: Now requires attribution + active billing. Eliminated.

---

## Infrastructure Requirements

### SearXNG Docker Setup

**Minimum `settings.yml` changes needed:**

```yaml
# Enable JSON API format
search:
  formats:
    - html
    - json        # ← Add this

# Recommended rate limiting (be polite to upstream engines)
engines:
  - name: google
    engine: google
    shortcut: g
    timeout: 3.0
    
# Optional: disable image-heavy engines for speed
```

**Docker Compose (`docker-compose.yml`):**

```yaml
version: "3"
services:
  searxng:
    image: searxng/searxng:latest
    container_name: searxng
    ports:
      - "8888:8080"     # Use 8888 to avoid conflicts
    volumes:
      - ./searxng-config:/etc/searxng:rw
    environment:
      - BASE_URL=http://localhost:8888/
      - INSTANCE_NAME=local-searxng
    restart: unless-stopped
```

**Auto-start on Mac:** Add a launchd plist or use `restart: unless-stopped` with
Docker Desktop's "Start Docker Desktop on login" option.

### Google Custom Search Setup

1. Go to https://programmablesearchengine.google.com/
2. Create a new search engine → enable "Search the entire web"
3. Note the Search Engine ID (`cx`)
4. Go to Google Cloud Console → Create API key for "Custom Search JSON API"
5. Set env vars:
   ```
   GOOGLE_CSE_API_KEY=<key>
   GOOGLE_CSE_ID=<cx>
   ```

---

## Migration Plan

1. **Week 1**: Set up SearXNG Docker locally. Test JSON API. Verify results quality.
2. **Week 1**: Set up Google CSE. Test fallback.
3. **Week 2**: Implement Python `searcher` library (spec in `04-python-spec.md`).
4. **Week 2**: Replace Brave API calls in OpenClaw's `web_search` tool config.
5. **Week 3**: Monitor, tune engine weights and rate limits.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| SearXNG upstream engines blocked | Medium | Low | Aggregation across 70+ engines; one block ≠ failure |
| Docker container crashes | Low | Medium | `restart: unless-stopped`; fallback to Google CSE |
| Google CSE quota exhausted (100/day) | Very Low | Low | Only used when SearXNG fails; add Serper as tertiary |
| SearXNG project abandoned | Very Low | High | Fork-friendly, simple codebase; alternatives exist |
| Mac offline (no Docker) | Low | High | For OpenClaw CLI: acceptable; add offline detection |

---

## Success Criteria

- Zero API cost after setup (excluding optional Google CSE paid tier if triggered)
- ≤5 second response time for 10 results (P90)
- 99%+ query success rate over a 30-day period
- Feature parity with Brave API: query, count, snippets, freshness filter
- Drop-in replacement for existing `web_search` tool calls
