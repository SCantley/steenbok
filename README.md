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
- **Browser automation** — Research support (arXiv, PubMed, JSTOR, Google Scholar). See `RISK-ASSESSMENT.md` for security considerations.

## Quick start (search proxy)

```bash
pip install -r requirements.txt
python src/search.py "your query"
python src/search.py --serve   # HTTP API on :8877
```

## Requirements

- macOS (Safari cookies)
- Full Disk Access for Terminal/IDE if using `browser-cookie3` (System Settings → Privacy & Security)
