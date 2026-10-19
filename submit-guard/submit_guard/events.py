"""What the guards record when they stop something."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BlockLayer = Literal["page_submit", "page_enter", "form_submit_call", "network", "navigation", "network_redirect"]


@dataclass(frozen=True)
class BlockEvent:
    layer: BlockLayer
    method: str | None = None
    host: str | None = None
    path: str | None = None          # never a query string
    operation_name: str | None = None


@dataclass(frozen=True)
class BlockedRequest:
    """A write request the network guard aborted, de-duplicated by method, host, path and operationName."""
    method: str
    host: str
    path: str
    operation_name: str | None
    submit_like: bool
    count: int


@dataclass(frozen=True)
class AllowedRequest:
    """A write request a rule let through, de-duplicated like BlockedRequest, counted by its response's
    status: 2xx (ok), 3xx, 4xx, 5xx, no response (failed), or none yet when the list was taken (pending). A 2xx is
    only the server taking the HTTP request; a GraphQL error usually comes back as 200 too."""
    method: str
    host: str
    path: str                       # never a query string
    operation_name: str | None
    ok: int
    redirected: int
    client_error: int
    server_error: int
    failed: int
    pending: int
