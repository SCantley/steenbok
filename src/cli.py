"""
CLI for Steenbok fetch. Run: python -m src.cli fetch <url>
"""

import argparse
import sys
from urllib.parse import unquote

from .fetch import (
    AllowlistError,
    ExtractionError,
    FetchError,
    URLBlockedError,
    fetch,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Steenbok fetch — safe URL text extraction for research"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch URL and extract text")
    fetch_parser.add_argument("url", help="URL to fetch")
    fetch_parser.add_argument(
        "--serve",
        action="store_true",
        help="Start HTTP server with /fetch endpoint",
    )
    fetch_parser.add_argument(
        "--port",
        type=int,
        default=8877,
        help="Port for --serve (default: 8877)",
    )

    args = parser.parse_args()

    if args.command == "fetch":
        if args.serve:
            _serve(args.port)
        else:
            _run_fetch(args.url)


def _run_fetch(url: str) -> None:
    try:
        text = fetch(url)
        print(text)
    except AllowlistError as e:
        print(f"AllowlistError: {e}", file=sys.stderr)
        sys.exit(2)
    except URLBlockedError as e:
        print(f"URLBlockedError: {e}", file=sys.stderr)
        sys.exit(3)
    except ExtractionError as e:
        print(f"ExtractionError: {e}", file=sys.stderr)
        sys.exit(4)
    except FetchError as e:
        print(f"FetchError: {e}", file=sys.stderr)
        sys.exit(1)


def _serve(port: int) -> None:
    from flask import Flask, request

    app = Flask(__name__)

    @app.route("/fetch")
    def handle_fetch():
        url_param = request.args.get("url")
        if not url_param:
            return {"error": "missing url"}, 400
        url = unquote(url_param)
        try:
            text = fetch(url)
            return text, 200, {"Content-Type": "text/plain; charset=utf-8"}
        except AllowlistError:
            return {"error": "URL not on allowlist"}, 403
        except URLBlockedError:
            return {"error": "URL blocked"}, 400
        except (ExtractionError, FetchError) as e:
            return {"error": str(e)}, 502

    print(f"[steenbok] fetch server at http://127.0.0.1:{port}/fetch?url=...")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
