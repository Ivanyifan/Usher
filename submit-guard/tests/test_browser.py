"""Guarded browser: lookup order, temporary profile removed on close."""
from submit_guard.browser import BROWSER_ENV, CANDIDATES, GuardedBrowser, browser_executable
from tests.support import other_server, playwright_instance, server  # noqa: F401


def test_lookup_order():
    custom = r"D:\Portable\chrome.exe"
    everything = {custom, *CANDIDATES}
    assert browser_executable({BROWSER_ENV: custom}, everything.__contains__) == custom
    assert browser_executable({}, everything.__contains__) == CANDIDATES[0]
    edge_only = {CANDIDATES[2]}
    assert browser_executable({}, edge_only.__contains__) == CANDIDATES[2]
    assert browser_executable({BROWSER_ENV: custom}, edge_only.__contains__) == CANDIDATES[2]  # missing file skipped
    assert browser_executable({}, set().__contains__) is None  # Playwright's own Chromium


def test_profile_is_temporary_and_removed(playwright_instance, server):
    guarded_browser = GuardedBrowser(playwright_instance, headless=True)
    profile = guarded_browser.profile_dir
    try:
        assert profile.is_dir() and profile.name.startswith("submit-guard-profile-")
        page = guarded_browser.context.pages[0] if guarded_browser.context.pages else guarded_browser.context.new_page()
        page.goto(server.url("form.html"))
        assert page.evaluate("navigator.serviceWorker ? navigator.serviceWorker.controller : null") is None
    finally:
        guarded_browser.close()
    assert not profile.exists()
