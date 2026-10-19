"""Without any guard, every trap on the challenge page really submits.

Each trap runs on a fresh page with only the action that springs it, and the test waits until
the local server has recorded that trap. This keeps the challenge honest: a guarded run that
shows zero submissions means the guards stopped real submissions, not dead traps.
"""
from __future__ import annotations

import time

import pytest
from playwright.sync_api import sync_playwright

from challenge.server import ChallengeServer
from submit_guard.browser import browser_executable


def _spring(page, trap: int) -> None:
    if trap == 1:
        page.fill("#name", "Jordan Example")
        page.press("#name", "Enter")
    elif trap == 2:
        page.click("#next")
    elif trap == 3:
        page.fill("#email", "jordan@example.com")
        page.click("#city")
    elif trap == 4:
        page.locator("#why").dispatch_event("input")
    elif trap == 5:
        frame = page.frame_locator("#referral")
        frame.locator("#code").fill("ABC123")
        frame.locator("#code").press("Tab")
    elif trap == 6:
        page.select_option("#source", "Friend")
    elif trap == 7:
        page.fill("#why", "I like the team.")
    elif trap == 8:
        page.click("#preview")
    elif trap == 9:
        page.wait_for_function("navigator.serviceWorker && navigator.serviceWorker.controller !== null", timeout=5000)
        page.fill("#city", "Spr")
    elif trap == 10:
        page.check("#terms")


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        executable = browser_executable()
        b = p.chromium.launch(**({"executable_path": executable} if executable else {}))
        yield b
        b.close()


@pytest.mark.parametrize("trap", range(1, 11))
def test_trap_submits_without_a_guard(browser, trap):
    with ChallengeServer() as server:
        context = browser.new_context()
        try:
            page = context.new_page()
            page.goto(server.url + "/")
            if trap == 9:
                # The worker controls the page only after a reload.
                page.wait_for_function("navigator.serviceWorker.ready.then(() => true)")
                page.reload()
            _spring(page, trap)
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                if any(r["trap"] == str(trap) for r in server.received):
                    break
                time.sleep(0.1)
            assert any(r["trap"] == str(trap) for r in server.received), server.received
        finally:
            context.close()
