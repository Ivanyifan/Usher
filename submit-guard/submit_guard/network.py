"""Network guard: only GET, HEAD and OPTIONS go through; every other method (POST, PUT,
PATCH, DELETE, and any custom one such as PURGE) is aborted unless it matches an AllowRule the caller passes. Installed on
the context, so iframes and pop-ups are covered too.

A write is "submit-like" when its path or GraphQL operationName contains a SUBMIT_REQUEST_WORDS entry, when it goes
to a graphql path whose operationName cannot be read, or when it goes to the address of the page or of the form's
frame (host and path, query ignored), which is where a plain form posts by default. The classification comes
first: a submit-like write is aborted and stops the run whatever rule it matches; rules only let through writes
that are not submit-like. The rest that match no rule (telemetry, for instance) are aborted and only listed. A
block is recorded before the abort. Every blocked write is listed in the report, de-duplicated by method, host,
path and operationName and counted.
A write let through by a rule is listed too (allowed_requests), counted by the status of its response: 2xx,
3xx, 4xx, 5xx, failed (no response: requestfailed), or still pending when the list is taken. Only the status code
is looked at, from the context's response and requestfailed events; no response header or body is read. A 2xx is
only the server taking the HTTP request: a GraphQL error usually comes back as 200 too. A let-through write
answered with 307 or 308 is sent again by the browser to the new address without passing the route, so it cannot
be stopped; such a response stops the run (a network_redirect event). The listeners come off with the route.
From a request body only the GraphQL operationName is ever read: the JSON body's top-level field, or the
"operations" part of a multipart body; file parts are never read. Nothing else from the body is read or logged.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import re
from urllib.parse import urlsplit

from submit_guard.words import SUBMIT_REQUEST_WORDS
from submit_guard.events import AllowedRequest, BlockedRequest, BlockEvent
from submit_guard.words import contains_substring

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SELFTEST_HOST = "submit-guard-selftest.invalid"
MAX_OPERATIONS_BYTES = 64 * 1024


@dataclass(frozen=True)
class AllowRule:
    method: str              # one method other than GET, HEAD and OPTIONS, e.g. "POST"
    host: str
    path_prefix: str
    operation_names: frozenset[str] | None = None   # for a GraphQL endpoint; None: operationName not looked at
    path_exact: bool = False   # True: the path must equal path_prefix, not just start with it

    def matches(self, method: str, host: str, path: str, operation_name: str | None) -> bool:
        if method != self.method or host != self.host:
            return False
        if not (path == self.path_prefix if self.path_exact else path.startswith(self.path_prefix)):
            return False
        return self.operation_names is None or operation_name in self.operation_names


# No rule by default: every write is aborted. A caller that needs a write the page makes while it is filled (an
# upload, a field the page saves as it goes) passes its own rules, as narrow as it can: one method, one host, an
# exact path, and for GraphQL the exact operation names. See examples/allow_rules.py.
ALLOW_RULES: tuple[AllowRule, ...] = ()
REDIRECT_STATUSES = frozenset({307, 308})   # the browser repeats method and body to the new address
_BUCKETS = ("ok", "redirected", "client_error", "server_error", "failed")


def _operation_from_json(data) -> str | None:
    if isinstance(data, dict):
        name = data.get("operationName")
        return name if isinstance(name, str) and name else None
    if isinstance(data, list):  # batched operations: all names, comma-joined
        names = [_operation_from_json(item) for item in data]
        return ",".join(name for name in names if name) or None
    return None


def operation_name(content_type: str, body: bytes | None) -> str | None:
    """The GraphQL operationName only; None when it cannot be read."""
    if not body:
        return None
    raw_type = content_type or ""
    content_type = raw_type.lower()
    try:
        if "multipart/form-data" in content_type:
            match = re.search(r'boundary="?([^";]+)"?', raw_type, re.IGNORECASE)  # the boundary is case-sensitive
            if not match:
                return None
            boundary = ("--" + match.group(1)).encode("latin-1")
            for part in body.split(boundary):
                head, _, rest = part.partition(b"\r\n\r\n")
                if re.search(rb'name="operations"', head, re.IGNORECASE) and b"filename=" not in head.lower():
                    text = rest[:MAX_OPERATIONS_BYTES].rstrip(b"\r\n-").decode("utf-8")
                    return _operation_from_json(json.loads(text))
            return None
        if "json" in content_type or body.lstrip()[:1] in (b"{", b"["):
            return _operation_from_json(json.loads(body[:MAX_OPERATIONS_BYTES * 16].decode("utf-8")))
    except (ValueError, UnicodeDecodeError):
        return None
    return None


def submit_like(path: str, operation: str | None) -> bool:
    if "graphql" in path.lower() and not operation:
        return True
    return bool(contains_substring(path, SUBMIT_REQUEST_WORDS) or contains_substring(operation, SUBMIT_REQUEST_WORDS))


def address(url: str) -> tuple[str, str]:
    """(host, path) of a URL, without query or fragment; the path without a trailing slash ("/" stays)."""
    parts = urlsplit(url)
    return parts.hostname or "", (parts.path or "/").rstrip("/") or "/"


class NetworkGuard:
    def __init__(self, rules: tuple[AllowRule, ...] = ALLOW_RULES):
        self._rules = rules
        self._context = None
        self._blocked: Counter = Counter()
        self._stop_events: list[BlockEvent] = []
        self._page_addresses: frozenset[tuple[str, str]] = frozenset()
        self.selftest_hits = 0
        # Let-through writes. Answered ones counted per (method, host, path, operation) and bucket; the ones
        # still waiting keyed by their Request object, with their key and sequence number.
        self._allowed: dict[tuple, Counter] = {}
        self._in_flight: dict = {}
        self._seq = 0
        self._failures = 0

    def install(self, context, page_urls=()) -> None:
        """page_urls: the URLs of the page and of the form's frame; a write to one of them is submit-like."""
        self._context = context
        self._page_addresses = frozenset(address(url) for url in page_urls if url)
        context.route("**/*", self._handle)
        context.on("response", self._on_response)
        context.on("requestfailed", self._on_failed)

    def remove(self) -> None:
        if self._context is not None:
            self._context.unroute("**/*", self._handle)
            self._context.remove_listener("response", self._on_response)
            self._context.remove_listener("requestfailed", self._on_failed)
            self._context = None

    def _handle(self, route, request) -> None:
        method = request.method.upper()
        if method in READ_METHODS:
            route.continue_()
            return
        parts = urlsplit(request.url)
        host, path = parts.hostname or "", parts.path or "/"
        operation = None
        if "graphql" in path.lower():
            operation = operation_name(request.headers.get("content-type", ""), request.post_data_buffer)
        # Record first: the abort is the last thing, so a failing abort cannot lose the record.
        if host == SELFTEST_HOST:
            self.selftest_hits += 1
        else:
            # Classified before the rules: no rule lets a submit-like write through.
            is_submit = address(request.url) in self._page_addresses or submit_like(path, operation)
            if not is_submit and any(rule.matches(method, host, path, operation) for rule in self._rules):
                key = (method, host, path, operation)
                self._seq += 1
                self._allowed.setdefault(key, Counter())
                self._in_flight[request] = (key, self._seq)
                route.continue_()
                return
            self._blocked[(method, host, path, operation, is_submit)] += 1
            if is_submit:
                self._stop_events.append(BlockEvent(layer="network", method=method, host=host, path=path,
                                                    operation_name=operation))
        route.abort("blockedbyclient")

    def drain(self) -> list[BlockEvent]:
        """The submit-like blocks since the last call; these stop the run."""
        events, self._stop_events = self._stop_events, []
        return events

    def quiet_blocks(self) -> int:
        """How many writes were blocked so far that were not submit-like (the ones only listed); writes let
        through by a rule are not counted, submit-like ones stop the run instead. Read-only."""
        return sum(count for (_, _, _, _, is_submit), count in self._blocked.items() if not is_submit)

    def _on_response(self, response) -> None:
        """The status of a let-through write; any other response is not looked at."""
        entry = self._in_flight.pop(response.request, None)
        if entry is None:
            return
        key, _ = entry
        status = response.status
        bucket = ("ok" if 200 <= status < 300 else "redirected" if 300 <= status < 400
                  else "client_error" if 400 <= status < 500 else "server_error")
        self._allowed[key][bucket] += 1
        if bucket != "ok":
            self._failures += 1
        if status in REDIRECT_STATUSES:
            method, host, path, operation = key
            self._stop_events.append(BlockEvent(layer="network_redirect", method=method, host=host, path=path,
                                                operation_name=operation))

    def _on_failed(self, request) -> None:
        """A let-through write that got no response."""
        entry = self._in_flight.pop(request, None)
        if entry is None:
            return
        key, _ = entry
        self._allowed[key]["failed"] += 1
        self._failures += 1

    def write_failures(self) -> int:
        """How many let-through writes so far got a status other than 2xx, or no response. Read-only."""
        return self._failures

    def allowed_writes(self) -> int:
        """How many writes were let through so far; the last one's sequence number. Read-only."""
        return self._seq

    def pending_since(self, seq: int) -> int:
        """How many writes let through after sequence number seq have no response yet. Read-only."""
        return sum(1 for _, number in self._in_flight.values() if number > seq)

    def allowed_requests(self) -> list[AllowedRequest]:
        pending = Counter(key for key, _ in self._in_flight.values())
        return [AllowedRequest(method=m, host=h, path=p, operation_name=o, **{b: counts[b] for b in _BUCKETS},
                               pending=pending[(m, h, p, o)])
                for (m, h, p, o), counts in sorted(self._allowed.items(),
                                                   key=lambda item: (item[0][0], item[0][1], item[0][2],
                                                                     item[0][3] or ""))]

    def blocked_requests(self) -> list[BlockedRequest]:
        return [BlockedRequest(method=m, host=h, path=p, operation_name=o, submit_like=s, count=n)
                for (m, h, p, o, s), n in sorted(self._blocked.items(),
                                                  key=lambda item: (item[0][0], item[0][1], item[0][2],
                                                                    item[0][3] or ""))]
