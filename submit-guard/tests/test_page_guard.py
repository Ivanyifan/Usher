"""In-page guard: while on, no way of submitting a fixture form gets through; after remove(),
reloads, new pages and new iframes carry no guard. Raw Playwright calls here simulate an agent bug."""
import pytest

from submit_guard.page import PageGuard
from tests.support import browser, no_navigation, other_server, page, playwright_instance, \
    server  # noqa: F401


def _submit_by(how, frame, form="#f", button="#typesubmit", field="#name"):
    if how == "button":
        frame.locator(button).click()
    elif how == "enter":
        frame.locator(field).focus()
        frame.locator(field).press("Enter")
    elif how == "submit_call":
        frame.evaluate(f"document.querySelector('{form}').submit()")
    elif how == "request_submit":
        frame.evaluate(f"document.querySelector('{form}').requestSubmit()")


@pytest.mark.parametrize("how, layer", [("button", "page_submit"), ("enter", "page_enter"),
                                        ("submit_call", "form_submit_call"), ("request_submit", "form_submit_call")])
def test_every_way_of_submitting_is_blocked(browser, page, server, how, layer):
    guard = PageGuard()
    guard.install(browser.context)
    page.goto(server.url("form.html"))
    navigations = no_navigation(page)
    _submit_by(how, page)
    page.wait_for_timeout(300)
    assert server.writes == 0 and navigations == [] and page.url == server.url("form.html")
    assert [event.layer for event in guard.drain()] == [layer]
    assert guard.drain() == []


@pytest.mark.parametrize("origin", ["same", "cross"])
def test_iframes_are_guarded_too(browser, page, server, other_server, origin):
    guard = PageGuard()
    guard.install(browser.context)
    query = "frame=same" if origin == "same" else f"frame=cross&port={other_server.port}"
    page.goto(server.url(f"form.html?{query}"))
    page.wait_for_selector("#child")
    child = page.frame_locator("#child")
    child.locator("#go").wait_for()
    frame = next(f for f in page.frames if f.url.endswith("/inner.html"))
    for how in ("button", "enter", "submit_call", "request_submit"):
        _submit_by(how, frame, form="#g", button="#go", field="#in")
    page.wait_for_timeout(300)
    assert server.writes == 0 and other_server.writes == 0
    assert sorted(event.layer for event in guard.drain()) == sorted(
        ["page_submit", "page_enter", "form_submit_call", "form_submit_call"])


def test_after_remove_submitting_works(browser, page, server):
    guard = PageGuard()
    guard.install(browser.context)
    page.goto(server.url("form.html"))
    guard.remove()
    page.locator("#name").fill("x")
    with page.expect_navigation():
        page.locator("#typesubmit").click()
    assert ("POST", "/submit") in server.requests and page.locator("#submitted").count() == 1


def test_drain_and_remove_before_install_do_nothing():
    guard = PageGuard()
    assert guard.drain() == []
    guard.remove()


def test_remove_clears_every_flag(browser, page, server):
    guard = PageGuard()
    guard.install(browser.context)
    page.goto(server.url("form.html"))
    assert page.evaluate("window.__submitGuardInstalled === true && window.__submitGuardGuard === true")
    guard.remove()
    assert page.evaluate("window.__submitGuardInstalled === false && window.__submitGuardGuard === false")


@pytest.mark.parametrize("after", ["reload", "new_page", "new_iframe"])
def test_nothing_comes_back_after_remove(browser, page, server, after):
    guard = PageGuard()
    guard.install(browser.context)
    page.goto(server.url("form.html"))
    assert guard.active_in(page.main_frame)
    guard.remove()
    if after == "reload":
        page.reload()
        frame, button, path = page.main_frame, "#typesubmit", "/submit"
    elif after == "new_page":
        page.goto(server.url("other.html"))
        frame, button, path = page.main_frame, "#send", "/other-submit"
    else:
        page.evaluate("""() => { const f = document.createElement('iframe'); f.id = 'late';
                                 f.src = '/inner.html'; document.body.appendChild(f); }""")
        page.frame_locator("#late").locator("#go").wait_for()
        frame = next(f for f in page.frames if f.url.endswith("/inner.html"))
        button, path = "#go", "/inner-submit"
    assert not guard.active_in(frame)
    frame.locator(button).click()
    page.wait_for_timeout(500)
    assert ("POST", path) in server.requests
    assert guard.drain() == []
