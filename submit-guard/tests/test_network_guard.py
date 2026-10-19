"""Network guard: every write is aborted unless allowed; submit-like ones stop the run; every blocked write is
listed once with a count. Test pages only; the hosts and operation names below are made up."""
import json

import pytest

from submit_guard.network import ALLOW_RULES, SELFTEST_HOST, AllowRule, NetworkGuard, address, operation_name, \
    submit_like
from submit_guard.stack import GuardStack, SubmitBlocked
from tests.support import browser, other_server, page, playwright_instance, server  # noqa: F401


def test_allow_rule_matching():
    rule = AllowRule("POST", "jobs.example.invalid", "/api/graphql", frozenset({"ApiAutocomplete"}))
    assert rule.matches("POST", "jobs.example.invalid", "/api/graphql", "ApiAutocomplete")
    assert not rule.matches("POST", "jobs.example.invalid", "/api/graphql", "ApiSubmitForm")
    assert not rule.matches("POST", "jobs.example.invalid", "/api/graphql", None)
    assert not rule.matches("PUT", "jobs.example.invalid", "/api/graphql", "ApiAutocomplete")
    assert not rule.matches("POST", "other.example.invalid", "/api/graphql", "ApiAutocomplete")
    assert not rule.matches("POST", "jobs.example.invalid", "/api/rest", "ApiAutocomplete")
    upload = AllowRule("PUT", "bucket.example.invalid", "/uploads/")
    assert upload.matches("PUT", "bucket.example.invalid", "/uploads/abc/def", None)


def _multipart(op, boundary="----fixture"):
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="operations"\r\n\r\n'
        + json.dumps({"operationName": op, "variables": {"file": None}}) + "\r\n",
        f'--{boundary}\r\nContent-Disposition: form-data; name="map"\r\n\r\n{{}}\r\n',
        f'--{boundary}\r\nContent-Disposition: form-data; name="0"; filename="fixture.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n%PDF fixture\r\n",
        f"--{boundary}--\r\n",
    ]
    return f"multipart/form-data; boundary={boundary}", "".join(parts).encode()


def test_operation_name_is_the_only_thing_read():
    assert operation_name("application/json", b'{"operationName": "ApiJobPosting", "variables": {}}') == "ApiJobPosting"
    assert operation_name("application/json", b'[{"operationName": "A"}, {"operationName": "B"}]') == "A,B"
    assert operation_name("application/json", b'{"query": "q"}') is None
    assert operation_name("application/json", b"not json") is None
    assert operation_name("text/plain", None) is None
    assert operation_name(*_multipart("ApiUploadFile")) == "ApiUploadFile"
    assert operation_name(*_multipart("ApiUploadFile", boundary="----WebKitFormBoundaryAbC")) == "ApiUploadFile"
    content_type, body = _multipart("ApiUploadFile")
    assert operation_name("multipart/form-data", body) is None  # no boundary: unreadable


@pytest.mark.parametrize("path, op, expected", [
    ("/collect", None, False),
    ("/api/public-graphql", "ApiJobPosting", False),
    ("/api/public-graphql", "SaveFieldValue", False),
    ("/api/public-graphql", "SaveFieldValueToFile", False),
    ("/api/public-graphql", None, True),                          # graphql without a readable operation
    ("/api/public-graphql", "SubmitApplicationForm", True),
    ("/embed/job_app", None, True),
    ("/boards/x/applications/1", None, True),
    ("/v1/submission", None, True),
    ("/candidates/new", None, True),
    ("/apply", None, True),
])
def test_submit_like(path, op, expected):
    assert submit_like(path, op) is expected


def _guarded(browser, page, server):
    page.goto(server.url("network.html"))
    guard = NetworkGuard()
    guard.install(browser.context)
    return guard


def test_address_drops_query_fragment_and_trailing_slash():
    assert address("https://jobs.example.invalid/acme/123/application?src=x#top") == (
        "jobs.example.invalid", "/acme/123/application")
    assert address("https://jobs.example.invalid/acme/") == ("jobs.example.invalid", "/acme")
    assert address("https://jobs.example.invalid") == ("jobs.example.invalid", "/")


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "PURGE"])
def test_writes_are_aborted_and_reads_pass(browser, page, server, method):
    guard = _guarded(browser, page, server)
    assert page.evaluate(f"window.writes.method('{method}')") == "blocked"
    assert page.evaluate("window.writes.get()") == "ok:200"
    assert server.writes == 0
    [blocked] = guard.blocked_requests()
    assert (blocked.method, blocked.path, blocked.submit_like, blocked.count) == (method, "/api/thing", False, 1)
    assert guard.drain() == []  # not submit-like: listed, does not stop


def test_graphql_operations_classify_and_stop(browser, page, server):
    guard = _guarded(browser, page, server)
    for call in ("graphqlJson('SaveFieldValue')", "graphqlJson('SaveFieldValue')", "graphqlJson(null)",
                 "graphqlJson('SubmitApplicationForm')", "graphqlMultipart('ApiUploadFile')",
                 "path('/collect')", "path('/collect')", "path('/embed/job_app')"):
        assert page.evaluate(f"window.writes.{call}") == "blocked"
    assert server.writes == 0
    rows = {(r.path, r.operation_name): (r.submit_like, r.count) for r in guard.blocked_requests()}
    assert rows == {
        ("/api/public-graphql", "SaveFieldValue"): (False, 2),
        ("/api/public-graphql", None): (True, 1),
        ("/api/public-graphql", "SubmitApplicationForm"): (True, 1),
        ("/api/graphql", "ApiUploadFile"): (False, 1),
        ("/collect", None): (False, 2),
        ("/embed/job_app", None): (True, 1),
    }
    stops = guard.drain()
    assert [(e.layer, e.path, e.operation_name) for e in stops] == [
        ("network", "/api/public-graphql", None),
        ("network", "/api/public-graphql", "SubmitApplicationForm"),
        ("network", "/embed/job_app", None),
    ]


def test_popups_iframes_and_beacons_are_covered(browser, page, server):
    guard = _guarded(browser, page, server)
    with page.context.expect_page() as popup_info:
        page.evaluate("window.writes.popup()")
    popup = popup_info.value
    popup.wait_for_load_state()
    assert popup.evaluate("window.done") == "blocked"
    page.evaluate("window.writes.iframe()")
    page.wait_for_selector("iframe")
    page.frame_locator("iframe").locator("script").wait_for(state="attached")
    inner = next(f for f in page.frames if f.url.endswith("/frame_post.html"))
    assert inner.evaluate("window.done") == "blocked"
    page.evaluate("window.writes.beacon()")
    page.wait_for_timeout(500)
    assert server.writes == 0
    paths = {r.path for r in guard.blocked_requests()}
    assert {"/popup-write", "/frame-write", "/beacon"} <= paths


def test_service_workers_cannot_take_requests_away(browser, page, server):
    page.goto(server.url("sw.html"))
    guard = NetworkGuard()
    guard.install(browser.context)
    registration = page.evaluate("window.registration")
    assert page.evaluate("navigator.serviceWorker ? navigator.serviceWorker.controller : null") is None
    assert page.evaluate("window.post()") == "blocked"
    assert server.writes == 0 and ("POST", "/sw-write") not in server.requests
    assert registration in ("refused", "registered", "unavailable", "pending")
    assert [r.path for r in guard.blocked_requests()] == ["/sw-write"]


def test_selftest_requests_are_counted_apart(browser, page, server):
    guard = _guarded(browser, page, server)
    probe = browser.context.new_page()
    probe.evaluate("""async (url) => { try { await fetch(url, {method: 'POST', body: 'x', mode: 'no-cors'}); }
                                       catch (e) {} }""", f"https://{SELFTEST_HOST}/")
    probe.close()
    assert guard.selftest_hits == 1 and guard.blocked_requests() == [] and guard.drain() == []


class _FailingRoute:
    def continue_(self):
        raise AssertionError("a write must not continue")

    def abort(self, reason):
        raise RuntimeError("abort failed")


class _Request:
    def __init__(self, method, url):
        self.method, self.url, self.headers, self.post_data_buffer = method, url, {}, b"x"


def test_a_block_is_recorded_before_the_abort():
    guard = NetworkGuard()
    for request in (_Request("POST", "http://127.0.0.1:1/apply"), _Request("PURGE", "http://127.0.0.1:1/cache"),
                    _Request("POST", f"https://{SELFTEST_HOST}/")):
        with pytest.raises(RuntimeError):
            guard._handle(_FailingRoute(), request)
    assert [(r.method, r.path, r.submit_like) for r in guard.blocked_requests()] == [
        ("POST", "/apply", True), ("PURGE", "/cache", False)]
    assert [e.path for e in guard.drain()] == ["/apply"] and guard.selftest_hits == 1


def test_a_write_to_the_page_address_stops_the_run(browser, page, server):
    stack = GuardStack(browser.context)
    page.goto(server.url("network.html?job=1"))
    stack.after_load(page)
    for call in ("path('/network.html?other=2')", "path('/network.html/')", "path('/collect')"):
        assert page.evaluate(f"window.writes.{call}") == "blocked"
    assert server.writes == 0
    with pytest.raises(SubmitBlocked) as blocked:
        stack.check()
    assert [(e.layer, e.path) for e in blocked.value.events] == [("network", "/network.html"),
                                                                ("network", "/network.html/")]
    rows = {r.path: (r.submit_like, r.count) for r in stack.network_guard.blocked_requests()}
    assert rows == {"/network.html": (True, 1), "/network.html/": (True, 1), "/collect": (False, 1)}
    stack.hand_over()


UPLOAD_HOST = "uploads.example.test"


def test_an_exact_path_rule_takes_that_path_only():
    exact = AllowRule("POST", UPLOAD_HOST, "/", path_exact=True)
    assert exact.matches("POST", UPLOAD_HOST, "/", None)
    for path in ("/x", "//", "/uploads"):
        assert not exact.matches("POST", UPLOAD_HOST, path, None)
    prefix = AllowRule("POST", UPLOAD_HOST, "/")   # without path_exact: a prefix
    assert all(prefix.matches("POST", UPLOAD_HOST, path, None) for path in ("/", "/x", "/uploads/a"))


def test_there_are_no_rules_by_default():
    assert ALLOW_RULES == ()
    assert NetworkGuard()._rules == ()


@pytest.mark.parametrize("method, host", [
    ("POST", UPLOAD_HOST + ".evil.invalid"), ("POST", "x." + UPLOAD_HOST),
    ("POST", "uploads.example.tes"), ("POST", UPLOAD_HOST.upper()),
    ("PUT", UPLOAD_HOST), ("PATCH", UPLOAD_HOST), ("DELETE", UPLOAD_HOST)])
def test_look_alike_hosts_and_other_methods_are_not_let_through(method, host):
    # Real hosts reach the guard lower-cased (urlsplit); the capitals only pin the match as plain equality.
    rule = AllowRule("POST", UPLOAD_HOST, "/", path_exact=True)
    assert not rule.matches(method, host, "/", None)


def _guarded_with(browser, page, server, rule, page_urls=()):
    page.goto(server.url("network.html"))
    guard = NetworkGuard((rule,))
    guard.install(browser.context, page_urls)
    return guard


def test_a_matching_write_goes_through_and_others_stay_blocked(browser, page, server):
    guard = _guarded_with(browser, page, server, AllowRule("POST", "127.0.0.1", "/", path_exact=True))
    assert page.evaluate("window.writes.path('/')") == "ok:200"
    assert server.writes == 1 and guard.blocked_requests() == []
    assert page.evaluate("window.writes.path('/collect')") == "blocked"
    assert server.writes == 1
    assert [(r.method, r.path, r.submit_like) for r in guard.blocked_requests()] == [("POST", "/collect", False)]
    assert guard.drain() == []


def test_no_rule_lets_a_submit_like_write_through(browser, page, server):
    guard = _guarded_with(browser, page, server, AllowRule("POST", "127.0.0.1", "/"))   # every path on the host
    assert page.evaluate("window.writes.path('/apply')") == "blocked"
    assert server.writes == 0
    assert [(r.path, r.submit_like) for r in guard.blocked_requests()] == [("/apply", True)]
    assert [(e.layer, e.path) for e in guard.drain()] == [("network", "/apply")]


def test_no_rule_lets_a_write_to_the_page_address_through(browser, page, server):
    guard = _guarded_with(browser, page, server, AllowRule("POST", "127.0.0.1", "/"),
                          page_urls=(server.url("network.html"),))
    assert page.evaluate("window.writes.path('/network.html')") == "blocked"
    assert server.writes == 0
    assert [(r.path, r.submit_like) for r in guard.blocked_requests()] == [("/network.html", True)]
    assert [(e.layer, e.path) for e in guard.drain()] == [("network", "/network.html")]


@pytest.mark.parametrize("method", ["POST", "PURGE"])
def test_remove_lets_writes_through(browser, page, server, method):
    guard = _guarded(browser, page, server)
    guard.remove()
    assert page.evaluate(f"window.writes.method('{method}')") == "ok:200"
    assert server.writes == 1


# A made-up GraphQL endpoint that saves fields and suggests locations while a form is filled.
FORMS = "forms.example.test"
FORMS_PATH = "/api/public-graphql"
FORMS_OPERATIONS = ("SuggestLocation", "CreateUploadHandle", "SaveFieldValue")
FORMS_RULE = AllowRule("POST", FORMS, FORMS_PATH, operation_names=frozenset(FORMS_OPERATIONS), path_exact=True)


def test_the_rule_takes_its_three_operations():
    for operation in FORMS_OPERATIONS:
        assert FORMS_RULE.matches("POST", FORMS, FORMS_PATH, operation)


@pytest.mark.parametrize("method, host, path", [
    ("POST", FORMS, FORMS_PATH + "/x"), ("POST", FORMS, FORMS_PATH + "x"), ("POST", FORMS, "/api/user-graphql"),
    ("POST", "www.example.test", FORMS_PATH), ("POST", FORMS + ".example", FORMS_PATH), ("PUT", FORMS, FORMS_PATH)])
def test_the_rule_takes_that_method_host_and_exact_path_only(method, host, path):
    assert not FORMS_RULE.matches(method, host, path, "SaveFieldValue")


@pytest.mark.parametrize("operation", ["SaveFieldValue,SaveFieldValue", "savefieldvalue", "ApiFixtureOther",
                                       None])
def test_the_rule_takes_its_exact_names_only(operation):
    # A batch's names come comma-joined (operation_name) and match none of the three.
    assert not FORMS_RULE.matches("POST", FORMS, FORMS_PATH, operation)


class _Route:
    def __init__(self):
        self.calls = []

    def continue_(self):
        self.calls.append("continue")

    def abort(self, reason):
        self.calls.append("abort")


class _JsonRequest:
    def __init__(self, url, body: bytes, method="POST"):
        self.method, self.url, self.post_data_buffer = method, url, body
        self.headers = {"content-type": "application/json"}


def _forms_write(guard, body: bytes) -> list[str]:
    route = _Route()
    guard._handle(route, _JsonRequest(f"https://{FORMS}{FORMS_PATH}", body))
    return route.calls


@pytest.mark.parametrize("operation", ["ApiSubmitFixtureForm", "ApiFixtureApplicationAction",
                                       "ApiSubmitFormValueToFile"])
def test_a_submit_like_operation_is_blocked_whatever_the_rule(operation):
    guard = NetworkGuard()
    assert _forms_write(guard, json.dumps({"operationName": operation}).encode()) == ["abort"]
    assert [(r.host, r.path, r.operation_name, r.submit_like) for r in guard.blocked_requests()] == [
        (FORMS, FORMS_PATH, operation, True)]
    assert [(e.layer, e.operation_name) for e in guard.drain()] == [("network", operation)]
    # Even a rule that takes exactly this name does not let it through: the submit-like check comes first.
    guard = NetworkGuard((AllowRule("POST", FORMS, FORMS_PATH, frozenset({operation}), path_exact=True),))
    assert _forms_write(guard, json.dumps({"operationName": operation}).encode()) == ["abort"]
    assert [(e.layer, e.operation_name) for e in guard.drain()] == [("network", operation)]


@pytest.mark.parametrize("body", [b"{}", b'{"query": "q"}', b"not json"])
def test_a_graphql_write_without_a_readable_operation_is_submit_like(body):
    guard = NetworkGuard()
    assert _forms_write(guard, body) == ["abort"]
    assert [(r.operation_name, r.submit_like) for r in guard.blocked_requests()] == [(None, True)]
    assert len(guard.drain()) == 1


def test_quiet_blocks_counts_the_blocked_writes_that_are_not_submit_like():
    guard = NetworkGuard((FORMS_RULE,))
    assert guard.quiet_blocks() == 0
    assert _forms_write(guard, json.dumps({"operationName": "ApiFixtureOther"}).encode()) == ["abort"]
    assert _forms_write(guard, json.dumps({"operationName": "ApiFixtureOther"}).encode()) == ["abort"]
    assert _forms_write(guard, json.dumps({"operationName": "ApiSubmitFixtureForm"}).encode()) == ["abort"]
    assert _forms_write(guard, json.dumps({"operationName": "SaveFieldValue"}).encode()) == ["continue"]
    assert guard.quiet_blocks() == 2
    assert len(guard.drain()) == 1 and guard.quiet_blocks() == 2      # drain() does not change the count
    stack = GuardStack(None, network_guard=guard)
    assert stack.quiet_blocks() == 2


# ---- What was let through and how it was answered ----

ROOT_RULE = AllowRule("POST", "127.0.0.1", "/", path_exact=True)


def test_a_root_rule_does_not_let_a_submit_like_write_through(browser, page, server):
    """The page's own address is the root here: submit-like, classified before the rule."""
    guard = _guarded_with(browser, page, server, ROOT_RULE, page_urls=(server.url(""),))
    assert page.evaluate("window.writes.path('/')") == "blocked"
    assert page.evaluate("window.writes.path('/apply')") == "blocked"
    assert server.writes == 0 and guard.allowed_requests() == [] and guard.allowed_writes() == 0
    assert [(e.layer, e.path) for e in guard.drain()] == [("network", "/"), ("network", "/apply")]


def _answered(page, guard):
    """Waits (at most 3 seconds) until every let-through write has its response event."""
    for _ in range(60):
        if not guard.pending_since(0):
            return
        page.wait_for_timeout(50)
    raise AssertionError("a let-through write got no response event")


def test_let_through_writes_are_counted_by_their_answer(browser, page, server):
    guard = _guarded_with(browser, page, server, ROOT_RULE)
    failures = []
    for query, shown in (("", "ok:200"), ("?fixture_status=403", "ok:403"), ("?fixture_status=500", "ok:500"),
                         ("?fixture_drop=1", "blocked")):
        assert page.evaluate(f"window.writes.path('/{query}')") == shown
        _answered(page, guard)
        failures.append(guard.write_failures())
    assert failures == [0, 1, 2, 3] and guard.allowed_writes() == 4 and server.writes == 4
    assert [(r.method, r.host, r.path, r.operation_name, r.ok, r.redirected, r.client_error, r.server_error,
             r.failed, r.pending) for r in guard.allowed_requests()] == [
        ("POST", "127.0.0.1", "/", None, 1, 0, 1, 1, 1, 0)]                  # the query strings are not kept
    assert guard.blocked_requests() == [] and guard.drain() == []


class _Response:
    def __init__(self, request, status):
        self.request, self.status = request, status


def test_a_let_through_write_without_an_answer_yet_is_pending():
    guard = NetworkGuard((AllowRule("POST", UPLOAD_HOST, "/", path_exact=True),))
    request = _JsonRequest(f"https://{UPLOAD_HOST}/", b"--fixture")
    route = _Route()
    guard._handle(route, request)
    assert route.calls == ["continue"] and guard.allowed_writes() == 1
    assert guard.pending_since(0) == 1 and guard.pending_since(1) == 0
    assert [(r.host, r.ok, r.pending) for r in guard.allowed_requests()] == [(UPLOAD_HOST, 0, 1)]
    guard._on_response(_Response(request, 204))
    assert guard.pending_since(0) == 0 and guard.write_failures() == 0
    assert [(r.ok, r.pending) for r in guard.allowed_requests()] == [(1, 0)]
    guard._on_response(_Response(request, 500))                               # answered once only
    guard._on_failed(_JsonRequest(f"https://{UPLOAD_HOST}/", b"x"))          # never let through: not counted
    assert [(r.ok, r.server_error, r.failed) for r in guard.allowed_requests()] == [(1, 0, 0)]


class _Context:
    def __init__(self):
        self.calls = []

    def route(self, pattern, handler):
        self.calls.append(("route", pattern, handler))

    def unroute(self, pattern, handler):
        self.calls.append(("unroute", pattern, handler))

    def on(self, event, handler):
        self.calls.append(("on", event, handler))

    def remove_listener(self, event, handler):
        self.calls.append(("remove_listener", event, handler))


def test_remove_takes_the_response_listeners_off_too():
    guard = NetworkGuard()
    context = _Context()
    guard.install(context)
    guard.remove()
    on = {(event, handler) for kind, event, handler in context.calls if kind == "on"}
    off = {(event, handler) for kind, event, handler in context.calls if kind == "remove_listener"}
    assert {event for event, _ in on} == {"response", "requestfailed"} and on == off


@pytest.mark.parametrize("status", [307, 308])
def test_a_let_through_write_redirected_with_its_body_stops_the_run(browser, page, server, status):
    """307 and 308 repeat the POST to the new address, and that one does not pass the route: the guard cannot
    stop it, only stop the run. The last assertion pins the gap: the repeated POST did reach the server."""
    guard = _guarded_with(browser, page, server, ROOT_RULE)
    assert page.evaluate(f"window.writes.path('/?fixture_redirect={status}')") == "ok:200"
    _answered(page, guard)
    assert [(r.path, r.redirected) for r in guard.allowed_requests()] == [("/", 1)]
    with pytest.raises(SubmitBlocked) as stopped:
        GuardStack(None, network_guard=guard).check()
    assert [(e.layer, e.method, e.host, e.path) for e in stopped.value.events] == [
        ("network_redirect", "POST", "127.0.0.1", "/")]
    assert server.requests[-2:] == [("POST", "/"), ("POST", "/fixture-landing")] and server.writes == 2


def test_a_let_through_write_redirected_with_303_only_counts_as_failed(browser, page, server):
    guard = _guarded_with(browser, page, server, ROOT_RULE)
    assert page.evaluate("window.writes.path('/?fixture_redirect=303')") == "ok:404"   # the landing is a GET
    _answered(page, guard)
    assert [(r.path, r.redirected) for r in guard.allowed_requests()] == [("/", 1)]
    assert guard.write_failures() == 1 and guard.drain() == [] and server.writes == 1
