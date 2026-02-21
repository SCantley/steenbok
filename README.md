# Steenbok

Browser automation and search tooling for research support. Designed for use with OpenClaw agents (Michelson, Feynman).

## Project layout

```
├── src/           # Source code
├── tests/         # Tests
├── docs/          # Additional documentation
├── project/plans/ # Plans (see PDRN standard)
└── scripts/       # Utility scripts
```

## Components

- **Google Search Proxy** — Safari-style proxy for Google search. See `simple-spec.md` for the full spec.
- **Safe Fetch** — Extract main text from URLs. Allowlist-protected, rate-limited (~5s between requests).
- **Browser automation** — Research support (arXiv, PubMed, JSTOR, Google Scholar). See `RISK-ASSESSMENT.md` for security considerations.

## Quick start (fetch)

```bash
pip install -r requirements.txt
python -m src fetch "https://en.wikipedia.org/wiki/Steenbok"
python -m src fetch --serve   # HTTP API on :8877
```

**Fetch API:** `GET http://localhost:8877/fetch?url=<encoded_url>` returns plain text.

**Allowlist:** Default domains include arxiv, pubmed, jstor, wikipedia, scholar, etc. Extend via `~/.steenbok/allowlist.txt` or `STEENBOK_ALLOWED_DOMAINS`.

## Requirements

- macOS (Safari cookies)
- Full Disk Access for Terminal/IDE if using `browser-cookie3` (System Settings → Privacy & Security)
