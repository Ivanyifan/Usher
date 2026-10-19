"""The challenge page with the guards on: what each trap does then, as it is, gaps included.

Each trap runs on a fresh guarded browser (GuardedBrowser: service workers blocked) in the order a run uses the
guards: page guard before goto, network guard and navigation watch after load, self-check, then the action. The
agent acts only through KeyGuard and ClickGuard, except where a test says it simulates an agent bug.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import sync_playwright

from challenge.server import ChallengeServer
from submit_guard import AllowRule, ClickGuard, ForbiddenClick, ForbiddenKey, GuardStack, KeyGuard, NetworkGuard, \
    SubmitBlocked
from submit_guard.browser import GuardedBrowser

KEYS, CLICKS = KeyGuard(), ClickGuard()


@pytest.fixture(scope="module")
def playwright_instance():
    with sync_playwright() as playwright:
        yield playwright


@pytest.fixture
def run(playwright_instance):
    with ChallengeServer() as server:
        browser = GuardedBrowser(playwright_instance, headless=True)
        try:
            page = browser.context.pages[0] if browser.context.pages else browser.context.new_page()
            stack = GuardStack(browser.context)
            stack.before_goto()
            page.goto(server.url + "/")
            stack.after_load(page)
            assert stack.selfcheck(page)
            yield page, stack, server
            stack.hand_over()
        finally:
            browser.close()


def _stops(stack) -> list[tuple[str, str | None]]:
    try:
        stack.check()
    except SubmitBlocked as blocked:
        return [(event.layer, event.path) for event in blocked.events]
    return []


def test_1_enter_is_never_sent(run):
    page, stack, server = run
    KEYS.type_text(page.locator("#name"), "Jordan Example")
    with pytest.raises(ForbiddenKey):
        KEYS.send_key(page.locator("#name"), "Enter")
    page.wait_for_timeout(500)
    assert _stops(stack) == [] and server.received == []


def test_1_a_raw_enter_is_swallowed_by_the_page_guard(run):
    page, stack, server = run
    page.locator("#name").press("Enter")   # an agent bug: a raw key, bypassing KeyGuard
    page.wait_for_timeout(500)
    assert _stops(stack) == [("page_enter", None)] and server.received == []


def test_2_a_button_with_no_type_is_never_clicked(run):
    page, stack, server = run
    with pytest.raises(ForbiddenClick, match="button_type_submit"):
        CLICKS.safe_click(page.locator("#next"))
    assert _stops(stack) == [] and server.received == []


def test_2_a_raw_click_on_it_is_stopped_by_the_page_guard(run):
    page, stack, server = run
    page.locator("#next").click()   # an agent bug: a raw click, bypassing ClickGuard
    page.wait_for_timeout(500)
    assert _stops(stack) == [("page_submit", None)] and server.received == []


def test_3_submit_on_blur(run):
    page, stack, server = run
    KEYS.type_text(page.locator("#email"), "jordan@example.com")
    CLICKS.safe_click(page.locator("#city"))
    page.wait_for_timeout(500)
    assert ("form_submit_call", None) in _stops(stack) and server.received == []


def test_4_request_submit_from_a_timer(run):
    page, stack, server = run
    KEYS.type_text(page.locator("#name"), "J")
    page.wait_for_timeout(3600)
    assert ("form_submit_call", None) in _stops(stack) and server.received == []


def test_5_a_form_inside_an_iframe(run):
    page, stack, server = run
    code = page.frame_locator("#referral").locator("#code")
    KEYS.type_text(code, "ABC123")
    KEYS.send_key(code, "Tab")
    page.wait_for_timeout(500)
    assert ("form_submit_call", None) in _stops(stack) and server.received == []


def test_6_a_fetch_post(run):
    page, stack, server = run
    page.select_option("#source", "Friend")
    page.wait_for_timeout(500)
    assert ("network", "/api/apply") in _stops(stack) and server.received == []


def test_7_send_beacon_is_aborted_and_only_listed(run):
    page, stack, server = run
    KEYS.type_text(page.locator("#why"), "Hi")
    page.wait_for_timeout(500)
    # /api/beacon is not submit-like, so the abort is listed and the run goes on.
    assert _stops(stack) == [] and stack.quiet_blocks() >= 1 and server.received == []
    assert ("POST", "/api/beacon") in {(r.method, r.path) for r in stack.network_guard.blocked_requests()}


def test_8_a_popup_that_submits(run):
    page, stack, server = run
    with page.context.expect_page() as popup:
        CLICKS.safe_click(page.locator("#preview"))
    popup.value.wait_for_load_state()
    popup.value.wait_for_timeout(1000)
    assert ("form_submit_call", None) in _stops(stack) and server.received == []


def test_9_a_service_worker_never_runs(run):
    page, stack, server = run
    assert page.evaluate("navigator.serviceWorker ? navigator.serviceWorker.controller : null") is None
    KEYS.type_text(page.locator("#city"), "Spr")
    page.wait_for_timeout(500)
    assert _stops(stack) == [] and server.received == []


def test_9_with_service_workers_allowed_the_network_guard_still_aborts_its_post(playwright_instance):
    with ChallengeServer() as server:
        browser = playwright_instance.chromium.launch(**_launch_options())
        try:
            context = browser.new_context()   # service workers allowed
            page = context.new_page()
            stack = GuardStack(context)
            stack.before_goto()
            page.goto(server.url + "/")
            page.wait_for_function("navigator.serviceWorker.ready.then(() => true)")
            page.reload()
            page.wait_for_function("navigator.serviceWorker.controller !== null")
            stack.after_load(page)
            assert stack.selfcheck(page)
            KEYS.type_text(page.locator("#city"), "Spr")
            page.wait_for_timeout(1000)
            assert ("network", "/api/apply") in _stops(stack) and server.received == []
            stack.hand_over()
        finally:
            browser.close()


def test_10_a_meta_refresh_is_detected_but_not_prevented(run):
    """A known gap: a GET navigation goes out. The navigation watch sees it and the run stops, but the server has
    already received the request."""
    page, stack, server = run
    CLICKS.safe_click(page.locator("#terms"))
    page.wait_for_timeout(2000)
    assert ("navigation", None) in _stops(stack)
    assert [(r["method"], r["path"]) for r in server.received] == [("GET", "/apply/confirm")]


def test_known_gap_a_307_on_an_allowed_write_stops_the_run_after_the_repeat_has_gone_out(playwright_instance):
    """A write the caller allows gets a 307 to a submit-like path; the browser repeats the POST there without the
    network guard seeing it. The guard sees the 307 and stops the run (network_redirect), but cannot stop the
    repeat: both halves are pinned, so the gap is detected, not prevented."""
    with ChallengeServer() as server:
        browser = GuardedBrowser(playwright_instance, headless=True)
        try:
            page = browser.context.pages[0] if browser.context.pages else browser.context.new_page()
            allow = AllowRule("POST", "127.0.0.1", "/api/save-and-redirect", path_exact=True)
            stack = GuardStack(browser.context, network_guard=NetworkGuard((allow,)))
            stack.before_goto()
            page.goto(server.url + "/")
            stack.after_load(page)
            assert stack.selfcheck(page)
            page.evaluate("fetch('/api/save-and-redirect', {method: 'POST', body: 'x'}).catch(() => {})")
            page.wait_for_timeout(1000)
            with pytest.raises(SubmitBlocked) as stopped:
                stack.check()
            assert [(e.layer, e.method, e.path) for e in stopped.value.events] == [
                ("network_redirect", "POST", "/api/save-and-redirect")]
            assert server.received == [{"method": "POST", "path": "/api/apply", "trap": "redirect"}]   # went out
        finally:
            browser.close()


def _launch_options() -> dict:
    from submit_guard.browser import browser_executable
    executable = browser_executable()
    return {"executable_path": executable} if executable else {}
