"""Local server for the ten-trap challenge page.

It serves the page and counts every submission that reaches it. A submission is any request
that is not GET, HEAD or OPTIONS, or a GET to /apply/confirm. The page reads the count from
GET /api/received, so the counter shows what the server actually received, not what the page
believes.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CONFIRM_PATH = "/apply/confirm"
REDIRECT_PATH = "/api/save-and-redirect"


class ChallengeServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.received: list[dict] = []
        self._lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def _record(self) -> None:
                parts = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                trap = parse_qs(parts.query).get("trap", [""])[0]
                if not trap and body:
                    trap = parse_qs(body.decode("utf-8", "replace")).get("trap", [""])[0]
                with server._lock:
                    server.received.append({"method": self.command, "path": parts.path, "trap": trap})

            def _send(self, status: int, body: bytes, kind: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def do_GET(self) -> None:
                parts = urlsplit(self.path)
                if parts.path == "/api/received":
                    with server._lock:
                        data = json.dumps(server.received).encode()
                    self._send(200, data, "application/json")
                    return
                if parts.path == "/api/cities":
                    self._send(200, b'["Springfield", "Riverton", "Lakeside"]', "application/json")
                    return
                if parts.path == CONFIRM_PATH:
                    self._record()
                    self._send(200, b"<h1>Confirm page</h1><p>This GET reached the server and was counted.</p>",
                               "text/html; charset=utf-8")
                    return
                name = parts.path.lstrip("/") or "index.html"
                target = (ROOT / name).resolve()
                if ROOT not in target.parents or not target.is_file() or target.suffix == ".py":
                    self._send(404, b"not found", "text/plain")
                    return
                kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                if kind.startswith("text/") or kind.endswith("javascript"):
                    kind += "; charset=utf-8"
                self._send(200, target.read_bytes(), kind)

            do_HEAD = do_GET

            def do_OPTIONS(self) -> None:
                self._send(204, b"", "text/plain")

            def _submission(self) -> None:
                if urlsplit(self.path).path == REDIRECT_PATH:
                    # Not a trap on the page: the known-gap test sends a write here that the caller allows.
                    length = int(self.headers.get("Content-Length") or 0)
                    if length:
                        self.rfile.read(length)
                    self.send_response(307)
                    self.send_header("Location", "/api/apply?trap=redirect")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self._record()
                self._send(200, b"<h1>Application submitted</h1>", "text/html; charset=utf-8")

            do_POST = do_PUT = do_PATCH = do_DELETE = _submission

        self._httpd = ThreadingHTTPServer((host, port), Handler)
        self.url = f"http://{host}:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def start(self) -> "ChallengeServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def __enter__(self) -> "ChallengeServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


if __name__ == "__main__":
    import time

    with ChallengeServer(port=8765) as s:
        print(f"Challenge page: {s.url}/  (Ctrl+C to stop)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
