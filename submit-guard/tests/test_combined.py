"""The guards together: an Enter that would submit a form (react-select with no highlighted option)
is stopped by each layer alone and by all three; the self-check and the navigation watch stop the run."""
import pytest

from submit_guard.keyboard import ForbiddenKey, KeyGuard
from submit_guard.network import NetworkGuard
from submit_guard.page import PageGuard
from submit_guard.stack import GuardStack, SubmitBlocked
from tests.support import browser, no_navigation, other_server, page, playwright_instance, \
    server  # noqa: F401


def _bug_presses_enter(page):
    """An agent bug: a raw Enter in the open dropdown, bypassing KeyGuard."""
    page.locator("#combo").focus()
    page.locator("#combo").press("Enter")
    page.wait_for_timeout(500)


def test_without_guards_the_fixture_really_submits(browser, page, server):
    page.goto(server.url("enter_submit.html"))
    with page.expect_navigation():
        page.locator("#combo").press("Enter")
    assert ("POST", "/enter-submit") in server.requests  # the fixture is a real trap


def test_all_three_layers_stop_the_run(browser, page, server):
    stack = GuardStack(browser.context)
    stack.before_goto()
    page.goto(server.url("enter_submit.html"))
    stack.after_load(page)
    assert stack.selfcheck(page)
    navigations = no_navigation(page)
    _bug_presses_enter(page)
    with pytest.raises(SubmitBlocked) as blocked:
        stack.check()
    assert [event.layer for event in blocked.value.events] == ["page_enter"]
    assert server.writes == 0 and navigations == []
    stack.hand_over()


def test_page_guard_alone(browser, page, server):
    guard = PageGuard()
    guard.install(browser.context)
    page.goto(server.url("enter_submit.html"))
    navigations = no_navigation(page)
    _bug_presses_enter(page)
    assert [event.layer for event in guard.drain()] == ["page_enter"]
    assert server.writes == 0 and navigations == []


def test_network_guard_alone(browser, page, server):
    page.goto(server.url("enter_submit.html"))
    guard = NetworkGuard()
    guard.install(browser.context)
    _bug_presses_enter(page)
    assert server.writes == 0
    [event] = guard.drain()
    assert (event.layer, event.method, event.path) == ("network", "POST", "/enter-submit")


def test_key_wrapper_alone(browser, page, server):
    page.goto(server.url("enter_submit.html"))
    with pytest.raises(ForbiddenKey):
        KeyGuard().send_key(page.locator("#combo"), "Enter")
    page.wait_for_timeout(300)
    assert server.writes == 0 and page.url == server.url("enter_submit.html")


def test_selfcheck_fails_without_the_network_guard(browser, page, server):
    stack = GuardStack(browser.context)
    stack.before_goto()
    page.goto(server.url("form.html"))
    assert stack.selfcheck(page) is False  # after_load never ran: nothing would be filled


def test_selfcheck_fails_without_the_page_guard(browser, page, server):
    stack = GuardStack(browser.context)
    page.goto(server.url("form.html"))  # before_goto skipped: frames with controls have no guard
    stack.after_load(page)
    assert stack.selfcheck(page) is False


@pytest.mark.parametrize("script", ["window.goElsewhere()", "window.pushUrl()"])
def test_navigation_after_the_guards_stops_the_run(browser, page, server, script):
    stack = GuardStack(browser.context)
    stack.before_goto()
    page.goto(server.url("navigate.html"))
    stack.after_load(page)
    assert stack.selfcheck(page)
    page.evaluate(script)
    page.wait_for_timeout(800)
    with pytest.raises(SubmitBlocked) as blocked:
        stack.check()
    assert "navigation" in [event.layer for event in blocked.value.events]
