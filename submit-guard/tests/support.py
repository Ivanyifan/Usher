"""pytest fixtures shared by the tests (imported by name).

`server` and `other_server` serve tests/pages on two ports (two origins); `browser` is a
GuardedBrowser (headless, temporary profile, service workers blocked) closed after each test; `page` is its
first page.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import sync_playwright

from submit_guard.browser import GuardedBrowser
from tests.server import FixtureServer


@pytest.fixture(scope="module")
def server():
    with FixtureServer() as running:
        yield running


@pytest.fixture(scope="module")
def other_server():
    with FixtureServer() as running:
        yield running


@pytest.fixture(scope="module")
def playwright_instance():
    with sync_playwright() as playwright:
        yield playwright


@pytest.fixture
def browser(playwright_instance, server, other_server):
    server.reset()
    other_server.reset()
    guarded_browser = GuardedBrowser(playwright_instance, headless=True)
    try:
        yield guarded_browser
    finally:
        guarded_browser.close()


@pytest.fixture
def page(browser):
    return browser.context.pages[0] if browser.context.pages else browser.context.new_page()


def no_navigation(page):
    """A list that collects main-frame navigations from now on."""
    seen = []
    page.on("framenavigated", lambda frame: seen.append(frame.url) if frame == page.main_frame else None)
    return seen
