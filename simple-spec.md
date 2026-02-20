# Simple Google Search Proxy — Safari Style

**Date:** 2026-02-18  
**Philosophy:** At 60 queries/day from one Mac, you ARE Safari. Be Safari.

---

## 1. Summary

A ~150-line Python script that proxies Google searches by pretending to be Safari on your Mac — same User-Agent, same headers, and crucially your actual Google cookies pulled straight from Safari's cookie store. Google sees a normal Safari request from a signed-in user and returns real results. You parse the HTML and return clean JSON. Run it as `python search.py "query"` for one-off lookups or `python search.py --serve` to start a local HTTP listener on port 8877. No Docker, no API keys, no accounts, nothing to maintain.

---

## 2. Getting Safari Cookies

Google cookies are the magic ingredient. Without them, Google might serve a consent wall or degraded results.

### Option A: `browser_cookie3` — Reads Safari's store directly (preferred)

```bash
pip install browser-cookie3
```

```python
import browser_cookie3
cookies = browser_cookie3.safari(domain_name='.google.com')
session.cookies = cookies
```

**One gotcha:** macOS may block access to `~/Library/Cookies/Cookies.binarycookies` unless Terminal (or whatever app is running this) has **Full Disk Access**. Grant it in System Settings → Privacy & Security → Full Disk Access. Then it just works.

### Option B: Manual export to `~/.google_cookies.json`

If `browser_cookie3` is annoying, export once and forget:

1. Open Safari, go to `google.com`, search for something
2. Open Web Inspector (Develop menu → Show Web Inspector → Storage → Cookies)
3. Find the `.google.com` cookies, manually copy these key ones:
   - `SOCS` or `CONSENT` — without this Google shows a consent wall
   - `NID` — preferences (language, safe search, etc.)
   - `SID`, `HSID`, `SSID` — login session (gives personalized results)
   - `1P_JAR` — targeting/preferences
4. Save as `~/.google_cookies.json`:

```json
[
  {"name": "SOCS", "value": "CAISNQgDEitb...", "domain": ".google.com"},
  {"name": "NID",  "value": "511=...", "domain": ".google.com"},
  {"name": "SID",  "value": "...", "domain": ".google.com"}
]
```

The code tries `browser_cookie3` first, falls back to the JSON file. Either works.

---

## 3. Exact Safari Headers

Safari on macOS sends these headers to Google. Copy them exactly — Google notices header fingerprints.

```python
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.3.1 Safari/605.1.15"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
}
```

**Note:** Safari does NOT send `Sec-Fetch-*` headers (those are Chromium-only). The above is the actual Safari request — no extras needed.

---

## 4. Google Search URL Structure

```
https://www.google.com/search?q={encoded_query}&num={n}&hl=en&gl=us
```

| Param | Meaning | Values |
|-------|---------|--------|
| `q`   | Query (URL-encoded) | `python+asyncio` |
| `num` | Results per page | `10` (default), up to `20` |
| `hl`  | Interface language | `en` |
| `gl`  | Country | `us` |
| `tbs` | Time filter | `qdr:d` (day), `qdr:w` (week), `qdr:m` (month), `qdr:y` (year) |
| `start` | Pagination offset | `0`, `10`, `20`... |

Example for time-filtered search:
```
https://www.google.com/search?q=AI+news&num=10&hl=en&gl=us&tbs=qdr:w
```

---

## 5. HTML Parsing Targets

Google's HTML is messy and changes periodically. Use structural selectors that survive class renames.

**Primary approach — structural (most stable):**

```python
from bs4 import BeautifulSoup

soup = BeautifulSoup(html, "html.parser")

# Each organic result is in a div.g
for g in soup.select("div.g"):
    title_el = g.select_one("h3")
    link_el  = g.select_one("a[href]")
    snip_el  = g.select_one("div.VwiC3b, span.aCOpRe, div[data-sncf]")
    
    if not (title_el and link_el):
        continue
    
    url = link_el["href"]
    if url.startswith("/url?q="):          # Google redirect links
        url = url.split("=", 1)[1].split("&")[0]
    if not url.startswith("http"):
        continue                            # Skip internal nav links
    
    results.append({
        "title":   title_el.get_text(strip=True),
        "url":     url,
        "snippet": snip_el.get_text(" ", strip=True) if snip_el else "",
    })
```

**If `div.g` breaks (Google renames it), fallback structural selector:**

```python
# "A div that contains a link that contains an h3"
for g in soup.select("div:has(> div > a[href] h3)"):
    ...
```

**Debugging when selectors break:**

```bash
python search.py "test" --dump-html | grep -i 'class="g"'
# Or save the raw HTML and inspect in browser
```

**Signs of a broken scrape:**
- Returns 0 results → check if HTML has a CAPTCHA or consent page
- `"did you mean"` page → query encoding issue
- Titles look like nav elements → selector is too broad

---

## 6. Flask Listener Design

```
GET http://localhost:8877/search?q=python+asyncio
GET http://localhost:8877/search?q=python+asyncio&n=5
```

Returns:
```json
[
  {"title": "Python asyncio — docs", "url": "https://...", "snippet": "..."},
  ...
]
```

That's the entire API. One endpoint, two params. The agent calls it exactly like it would call any search API.

**Server design:**
```python
from flask import Flask, request, jsonify
app = Flask(__name__)

@app.route("/search")
def handle_search():
    q = request.args.get("q", "").strip()
    n = int(request.args.get("n", 10))
    if not q:
        return jsonify({"error": "missing q"}), 400
    return jsonify(do_search(q, n))

app.run(host="127.0.0.1", port=8877, debug=False)
```

**To run as a persistent daemon**, just keep the terminal open or use a launchd plist (optional, do later if needed).

---

## 7. CLI Interface

```bash
# One-off query (prints human-readable)
python search.py "python asyncio tutorial"

# One-off query, JSON output
python search.py "python asyncio tutorial" --json

# Specify result count
python search.py "AI news" --n 5

# Time filter
python search.py "AI news" --time week

# Start the HTTP server
python search.py --serve

# Custom port
python search.py --serve --port 9000

# Debug: save raw HTML to see what Google returned
python search.py "test" --dump-html > /tmp/google.html
```

---

## 8. Rate Limiting & Multi-Agent Queueing

**Basic rate limiting:**
```python
import time
time.sleep(1)  # after every request
```

At 60 queries/day that's 1 request per 24 minutes on average — laughably safe.

**Multi-agent queueing (IMPORTANT):**

When multiple agents/subagents might be searching simultaneously, we need a queue to:
1. Prevent crossed responses (agent A's result going to agent B)
2. Maintain human-like pacing
3. Keep requests serialized

**Queue design — one request every 10 seconds max:**

```python
import threading
import queue
import random
from dataclasses import dataclass

@dataclass
class SearchRequest:
    query: str
    n: int
    time_filter: str
    response_event: threading.Event
    result: list = None

REQUEST_QUEUE = queue.Queue()
DRAIN_INTERVAL = 5.0  # base seconds between requests
DRAIN_JITTER   = 0.4  # +/- randomization

def queue_worker():
    """Drains the queue, one request every DRAIN_INTERVAL seconds."""
    while True:
        req = REQUEST_QUEUE.get()
        req.result = do_search_internal(req.query, req.n, req.time_filter)
        req.response_event.set()
        time.sleep(DRAIN_INTERVAL + random.uniform(-DRAIN_JITTER, DRAIN_JITTER))

# Start worker thread on import
threading.Thread(target=queue_worker, daemon=True).start()

def do_search(query: str, n: int = 10, time_filter: str = None) -> list[dict]:
    """Queued search — blocks until this request is processed."""
    req = SearchRequest(query, n, time_filter, threading.Event())
    REQUEST_QUEUE.put(req)
    req.response_event.wait()  # block until our turn
    return req.result
```

**What this gives you:**
- Agent A submits search → queued
- Agent B submits search → queued behind A
- Worker drains queue every ~5 seconds (±0.4s jitter for human-like timing)
- Each agent blocks until ITS request completes
- No crossed responses, max ~12 queries/minute even under burst

If you ever get blocked (you'll see 0 results or a CAPTCHA), increase DRAIN_INTERVAL or take a break.

---

## 9. Complete Code

This is close to actual working Python. Cursor it into shape.

```python
#!/usr/bin/env python3
"""
search.py — Safari-style Google search proxy
Usage:
  python search.py "query"              # CLI, human-readable
  python search.py "query" --json       # CLI, JSON output
  python search.py "query" --n 5        # fewer results
  python search.py "query" --time week  # time filter
  python search.py --serve              # HTTP server on :8877
  python search.py "query" --dump-html  # debug: print raw HTML
"""

import json, os, sys, time, argparse
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup

# ─── Config ────────────────────────────────────────────────────────────────

PORT         = 8877
COOKIES_FILE = os.path.expanduser("~/.google_cookies.json")
SLEEP_SEC    = 1   # between requests — don't touch this

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.3.1 Safari/605.1.15"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
}

TIME_FILTERS = {
    "day": "qdr:d", "week": "qdr:w", "month": "qdr:m", "year": "qdr:y"
}

# ─── Session ────────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)

    # Try reading Safari cookies directly
    try:
        import browser_cookie3
        s.cookies = browser_cookie3.safari(domain_name=".google.com")
        print("[search] loaded Safari cookies via browser_cookie3", file=sys.stderr)
        return s
    except Exception as e:
        print(f"[search] browser_cookie3 failed ({e}), trying JSON fallback", file=sys.stderr)

    # Fall back to JSON cookie file
    if os.path.exists(COOKIES_FILE):
        with open(COOKIES_FILE) as f:
            for c in json.load(f):
                s.cookies.set(c["name"], c["value"], domain=c.get("domain", ".google.com"))
        print(f"[search] loaded cookies from {COOKIES_FILE}", file=sys.stderr)
    else:
        print(f"[search] WARNING: no cookies found — results may be degraded", file=sys.stderr)

    return s

SESSION = make_session()

# ─── Core ────────────────────────────────────────────────────────────────────

def do_search(query: str, n: int = 10, time_filter: str = None) -> list[dict]:
    params = {"q": query, "num": n, "hl": "en", "gl": "us"}
    if time_filter and time_filter in TIME_FILTERS:
        params["tbs"] = TIME_FILTERS[time_filter]

    try:
        r = SESSION.get("https://www.google.com/search", params=params, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"[search] fetch error: {e}", file=sys.stderr)
        return []

    time.sleep(SLEEP_SEC)
    return parse_results(r.text)[:n]


def parse_results(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for g in soup.select("div.g"):
        title_el = g.select_one("h3")
        link_el  = g.select_one("a[href]")
        snip_el  = g.select_one("div.VwiC3b, span.aCOpRe, div[data-sncf]")

        if not (title_el and link_el):
            continue

        url = link_el.get("href", "")
        if url.startswith("/url?q="):
            url = url.split("=", 1)[1].split("&")[0]
        if not url.startswith("http"):
            continue

        results.append({
            "title":   title_el.get_text(strip=True),
            "url":     url,
            "snippet": snip_el.get_text(" ", strip=True) if snip_el else "",
        })

    return results

# ─── Server ──────────────────────────────────────────────────────────────────

def serve(port: int = PORT):
    from flask import Flask, request, jsonify
    app = Flask(__name__)

    @app.route("/search")
    def handle_search():
        q    = request.args.get("q", "").strip()
        n    = int(request.args.get("n", 10))
        time = request.args.get("time")   # day/week/month/year
        if not q:
            return jsonify({"error": "missing q"}), 400
        return jsonify(do_search(q, n, time))

    print(f"[search] serving at http://localhost:{port}/search?q=...")
    app.run(host="127.0.0.1", port=port, debug=False)

# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Safari-style Google search proxy")
    p.add_argument("query", nargs="?",  help="Search query")
    p.add_argument("--serve",      action="store_true", help="Start HTTP server")
    p.add_argument("--port",       type=int, default=PORT)
    p.add_argument("--n",          type=int, default=10, help="Number of results")
    p.add_argument("--time",       choices=["day","week","month","year"], default=None)
    p.add_argument("--json",       dest="as_json", action="store_true")
    p.add_argument("--dump-html",  action="store_true", help="Print raw HTML and exit")
    args = p.parse_args()

    if args.serve:
        serve(args.port)
        return

    if not args.query:
        p.print_help()
        return

    if args.dump_html:
        params = {"q": args.query, "num": args.n, "hl": "en", "gl": "us"}
        r = SESSION.get("https://www.google.com/search", params=params, timeout=10)
        print(r.text)
        return

    results = do_search(args.query, args.n, args.time)

    if args.as_json:
        print(json.dumps(results, indent=2))
    else:
        for i, r in enumerate(results, 1):
            print(f"{i}. {r['title']}")
            print(f"   {r['url']}")
            if r["snippet"]:
                print(f"   {r['snippet'][:120]}")
            print()

if __name__ == "__main__":
    main()
```

---

## 10. Installation

```bash
# Dependencies — that's it
pip install requests beautifulsoup4 flask browser-cookie3

# Test it immediately
python search.py "test query"

# If you get 0 results:
python search.py "test" --dump-html > /tmp/google.html
open /tmp/google.html  # Is it a consent wall? CAPTCHA? Verify HTML looks normal.
```

**If `browser_cookie3` fails (Full Disk Access not granted):**
1. System Settings → Privacy & Security → Full Disk Access → add Terminal (or your IDE)
2. Re-run

**If selectors break (Google updated their HTML):**
```bash
python search.py "test" --dump-html > /tmp/google.html
# Open in browser, inspect element, find the result containers
# Update the select() calls in parse_results()
```

---

## 11. OpenClaw Integration

Once `--serve` is running on port 8877, call it like any HTTP API:

```
GET http://localhost:8877/search?q=python+asyncio
GET http://localhost:8877/search?q=AI+news&n=5&time=week
```

Returns `[{"title", "url", "snippet"}, ...]` — same shape as Brave was returning. Drop-in replacement.

Keep the server running in a terminal tab, or add a launchd plist later if you want it auto-starting.
