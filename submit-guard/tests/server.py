"""Local HTTP server for the test pages.

Serves tests/pages on 127.0.0.1 with a free port. Every request's method and path is recorded;
`writes` counts every method other than GET, HEAD and OPTIONS (POST, PUT, PATCH, DELETE and the custom PURGE
are served). A write gets a small "submitted" page, so a real submission would
also show on the page. CORS is open so a second server can serve a cross-origin iframe.
For tests only, a write's query string can change the answer (without one, nothing changes):
fixture_delay=N waits N seconds first (at most 5); fixture_drop=1 closes the connection without any answer;
fixture_redirect=303, 307 or 308 answers with that status and Location: /fixture-landing; fixture_status=NNN
answers with that status.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, urlsplit

PAGES = Path(__file__).resolve().parent / "pages"
SUBMITTED = b"<!doctype html><html><body><h1 id='submitted'>submitted</h1></body></html>"
READ_METHODS = ("GET", "HEAD", "OPTIONS")


class _Handler(BaseHTTPRequestHandler):
    server: "_Server"

    def log_message(self, *args):  # quiet
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, PURGE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def _record(self):
        with self.server.lock:
            self.server.requests.append((self.command, urlsplit(self.path).path))

    def do_GET(self):
        self._record()
        name = urlsplit(self.path).path.lstrip("/") or "index.html"
        target = (PAGES / name).resolve()
        if PAGES not in target.parents or not target.is_file():
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        body = target.read_bytes()
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            kind = "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _write(self):
        self._record()
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        query = {key: values[0] for key, values in parse_qs(urlsplit(self.path).query).items()}
        if "fixture_delay" in query:
            time.sleep(min(float(query["fixture_delay"]), 5.0))
        if query.get("fixture_drop") == "1":
            self.close_connection = True
            return
        if query.get("fixture_redirect") in ("303", "307", "308"):
            self.send_response(int(query["fixture_redirect"]))
            self.send_header("Location", "/fixture-landing")
            self.send_header("Content-Length", "0")
            self._cors()
            self.end_headers()
            return
        self.send_response(int(query.get("fixture_status", 200)))
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(SUBMITTED)))
        self._cors()
        self.end_headers()
        self.wfile.write(SUBMITTED)

    do_POST = do_PUT = do_PATCH = do_DELETE = do_PURGE = _write

    def do_OPTIONS(self):
        self._record()
        self.send_response(204)
        self._cors()
        self.end_headers()


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.requests: list[tuple[str, str]] = []
        self.lock = threading.Lock()


class FixtureServer:
    def __init__(self):
        self._server = _Server()
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "FixtureServer":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def url(self, path: str = "") -> str:
        return f"http://127.0.0.1:{self.port}/{path.lstrip('/')}"

    @property
    def requests(self) -> list[tuple[str, str]]:
        with self._server.lock:
            return list(self._server.requests)

    @property
    def writes(self) -> int:
        return sum(1 for method, _ in self.requests if method not in READ_METHODS)

    def reset(self) -> None:
        with self._server.lock:
            self._server.requests.clear()
