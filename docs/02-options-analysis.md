# Options Analysis: Web Search Alternatives

**Project:** Brave Search API Replacement  
**Date:** 2026-02-17  
**Research basis:** Web research conducted Feb 17–18, 2026

---

## Context: Why We're Replacing Brave

Brave Search API dropped its free tier ~Feb 12–13, 2026:
- Old free tier: 2,000–5,000 queries/month, hard capped, card "never charged"
- New "free": $5/month credit (~1,000 queries), requires **public attribution on your website**,  
  card auto-billed above that with no spending cap
- Effectively, Brave is now paid-only with a small subsidy that requires attribution
- Brave is also the **only remaining independent Western search index** (Bing API was killed Aug 2025)

This makes the timing of this project critical.

---

## Options Evaluated

### Option A: SearXNG (Self-Hosted)

**What it is:** Open-source metasearch engine. Aggregates results from 70+ engines
(Google, Bing, DuckDuckGo, Startpage, etc.) and returns them via a JSON API.
You run it on your own machine or server.

**How it works:**
- Deploy via Docker (`docker run searxng/searxng`)
- Enable JSON format in `settings.yml`
- Query: `GET http://localhost:8080/search?q=<query>&format=json`
- Returns: list of results with url, title, content (snippet), publishedDate, engine

**API shape:**
```json
{
  "query": "python async",
  "number_of_results": 1200000,
  "results": [
    {
      "url": "https://example.com",
      "title": "Example",
      "content": "Snippet text...",
      "publishedDate": "2025-01-01T00:00:00",
      "engine": "google",
      "score": 0.9,
      "category": "general"
    }
  ]
}
```

**Parameters supported:**
- `q`: query string
- `categories`: general, news, images, etc.
- `engines`: comma-separated list of engines to use
- `language`: e.g., `en`
- `time_range`: `day`, `month`, `year`
- `safesearch`: 0, 1, 2
- `pageno`: page number

**Pros:**
- ✅ **Completely free** — no API keys, no limits, no account
- ✅ **Privacy preserving** — all queries go through your instance, not tied to your IP
- ✅ **Result diversity** — aggregates multiple engines, de-duplicates
- ✅ **Full web search** — not instant answers only
- ✅ **Actively maintained** (as of Feb 2026)
- ✅ **Used in production** by LangChain, LiteLLM, Open WebUI, Perplexica
- ✅ **Time range filtering** supported by many engines
- ✅ **Docker Compose setup** is one command
- ✅ **No ToS violation** — SearXNG itself runs search queries the way a browser would

**Cons:**
- ⚠️ **Requires Docker** — adds a runtime dependency
- ⚠️ **Rate limited by upstream engines** — Google/Bing will 429 or block if you hammer it.  
  SearXNG uses request delays and engine rotation to mitigate this.
- ⚠️ **Result quality varies** — depends on which engines are enabled and their current state
- ⚠️ **JSON format disabled by default** — must explicitly enable in `settings.yml`
- ⚠️ **Cold start** — container takes ~5–10s to start; keep it running persistently
- ⚠️ **No SLA** — if upstream engines change their HTML, SearXNG engines may break  
  (but the project actively patches these)
- ⚠️ **403 errors** — some engines block SearXNG instances. Need to configure engines carefully.

**Rate limiting implications:**
SearXNG spaces out requests to individual engines internally. At 60 queries/day we are well
within safe operating range. At 200/day we might see occasional soft-blocking by Google,
but SearXNG rotates across engines automatically. For safety, we add client-side
throttling in our wrapper (≤1 req/sec to SearXNG, which it handles gracefully).

**Setup complexity:** Low. One `docker compose up -d`, edit `settings.yml` to enable JSON.

**Verdict:** ✅ **Best primary backend.**

---

### Option B: Google Custom Search JSON API

**What it is:** Official Google API for querying a Programmable Search Engine (PSE).
Free tier: 100 queries/day. Paid: $5 per 1,000 queries.

**How it works:**
```
GET https://customsearch.googleapis.com/customsearch/v1
  ?key=<API_KEY>
  &cx=<SEARCH_ENGINE_ID>
  &q=<query>
  &num=10
```

**Caveats:**
- Must create a Google Cloud project and API key
- Must create a Programmable Search Engine at cse.google.com
- PSE by default only searches sites you configure — to search the whole web,
  you enable "Search the entire web" in PSE settings
- Even then, results are curated by Google's PSE index, which may differ from google.com
- 100 queries/day free (~3,000/month) — fine for fallback, not for primary

**Pros:**
- ✅ Official, stable API (Google maintains it)
- ✅ 100 free queries/day — good enough as a fallback
- ✅ Reliable, fast, high-quality results
- ✅ Simple HTTP API with well-documented response schema
- ✅ Time-based filtering via `dateRestrict` param
- ✅ No ToS issues — it's an official paid API

**Cons:**
- ❌ 100/day free limit — insufficient as primary (we use ~60/day *average*, but can burst)
- ❌ Requires Google account + project setup
- ❌ PSE results may not perfectly match google.com results
- ❌ Snippets are sometimes short; no `publishedDate` reliably
- ❌ Paid tier ($5/1,000) is reasonable but adds cost if fallback triggers frequently

**Rate limiting implications:**
100/day hard limit. Must track daily usage. Ideal as a safety net, not day-to-day driver.

**Verdict:** ✅ **Good secondary/fallback backend.** Register one now; keep the key in env.

---

### Option C: DuckDuckGo (duckduckgo-search library)

**What it is:** Unofficial Python library (`duckduckgo-search`, `pip install duckduckgo-search`)
that scrapes DuckDuckGo's search interface. Not an official API.

**How it works:**
```python
from duckduckgo_search import DDGS
results = DDGS().text("python async", max_results=10)
```

**Rate limiting reality (2025–2026):**
Multiple projects (Open WebUI, CrewAI, Agno) report `RatelimitException: 202 Ratelimit`
errors. DuckDuckGo actively detects and blocks programmatic access.
The library maintainer rotates backends (`api` → `lite` → `html`) but blocking is frequent
and unpredictable. This is a fragile dependency for production use.

**Pros:**
- ✅ Zero setup — pure Python, no keys
- ✅ Good result quality (DuckDuckGo)
- ✅ Actively maintained library

**Cons:**
- ❌ **Unofficial / ToS gray area** — DuckDuckGo does not provide a public search API
- ❌ **Frequently rate-limited** — documented in many production systems
- ❌ **Brittle** — breaks when DDG changes their response format
- ❌ **No time range filtering** reliably
- ❌ **No guaranteed snippet quality**

**Verdict:** ❌ **Not recommended.** Too fragile for production, ToS questionable.
Could be a last-resort tertiary fallback with heavy retry/backoff.

---

### Option D: Serper.dev

**What it is:** Paid Google SERP API. Fast, reliable. $1/1,000 queries.
Offers 2,500 free searches on signup (one-time, not recurring).

**Pros:**
- ✅ Google-quality results
- ✅ Extremely fast (1–2s)
- ✅ Simple API
- ✅ 2,500 free on signup for testing

**Cons:**
- ❌ One-time free, then paid
- ❌ $1/1,000 = $0.06/day at our rate — cheap but nonzero
- ❌ External dependency

**Verdict:** 🟡 Optional tertiary fallback if we register an account. Good for testing.
Not worth as primary — defeats the "free" goal once the signup bonus expires.

---

### Option E: Exa.ai

**What it is:** Neural search API focused on AI use cases. Indexes the web with
neural embeddings. $2.50/1,000 queries.

**Pros:**
- ✅ AI-native — returns semantically similar results
- ✅ Content extraction included (full page text)

**Cons:**
- ❌ Paid — no meaningful free tier
- ❌ Semantically focused, may miss exact keyword matches
- ❌ Different result model than standard web search

**Verdict:** ❌ Out of scope. Interesting tool but not a drop-in replacement.

---

### Option F: Tavily

**What it is:** AI search API. $8/1,000 queries. Designed for LLM grounding.

**Pros:**
- ✅ Includes page content extraction
- ✅ Good with LangChain/LlamaIndex

**Cons:**
- ❌ Expensive relative to needs ($8/1,000 vs Brave's $5/1,000)
- ❌ No free tier

**Verdict:** ❌ Too expensive. Not recommended.

---

### Option G: Bing Web Search API (Azure)

**What it is:** Microsoft's official search API via Azure Cognitive Services.

**Status:** Shut down August 2025. No longer available.

**Verdict:** ❌ Unavailable.

---

### Option H: Startpage / Qwant / Mojeek Direct Scraping

These are privacy-focused search engines. None offer a documented API.
Scraping them would be fragile and likely ToS-violating.

**Verdict:** ❌ Not recommended as standalone. They're upstream engines inside SearXNG,
which is the correct way to use them.

---

## Comparison Matrix

| Option | Cost | Setup | Reliability | Quality | Safe (ToS) | Free Tier |
|--------|------|-------|-------------|---------|------------|-----------|
| **SearXNG (self-hosted)** | Free | Medium | High | Good | ✅ | Unlimited |
| Google Custom Search | Free then $5/1k | Low | Very High | Excellent | ✅ | 100/day |
| DuckDuckGo (lib) | Free | Very Low | Low | Good | ⚠️ | Unlimited* |
| Serper.dev | $1/1k | Low | Very High | Excellent | ✅ | 2,500 once |
| Exa.ai | $2.50/1k | Low | High | Neural | ✅ | Limited |
| Tavily | $8/1k | Low | High | Good | ✅ | None |
| Bing API | N/A | N/A | N/A | N/A | ✅ | **Shut down** |

*DuckDuckGo "unlimited" is theoretical — rate limiting is real and unpredictable.

---

## Key Insight

The combination of **SearXNG (self-hosted) + Google Custom Search API (fallback)**
covers all requirements:
- Zero ongoing cost for 99%+ of queries (via SearXNG)
- Official, reliable fallback (Google CSE, 100/day)
- No ToS violations
- Full web search, time filtering, structured output
- Runs on Steve's Mac, starts with Docker, survives reboots
