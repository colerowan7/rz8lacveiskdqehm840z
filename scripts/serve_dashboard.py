"""
Serves the dashboard locally and opens it in your browser.

Usage:
    python scripts/serve_dashboard.py
"""

import http.server
import webbrowser
from pathlib import Path

PORT = 8765
ROOT = Path(__file__).resolve().parent.parent


class Handler(http.server.SimpleHTTPRequestHandler):
    """Disables caching so the dashboard always reflects the latest
    code/data, even across `pull_league_data.py` / `analyze.py` re-runs
    without restarting this server."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()


def main():
    url = f"http://localhost:{PORT}/frontend/index.html"
    # ThreadingHTTPServer, not plain HTTPServer: a browser opens several
    # parallel/keep-alive connections per page load, and a single-threaded
    # server can get stuck on one of them (looks "up" in a port check but
    # refuses new connections). Threading avoids that class of hang.
    with http.server.ThreadingHTTPServer(("", PORT), Handler) as httpd:
        print(f"Serving dashboard at {url}")
        print("Press Ctrl+C to stop.")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
