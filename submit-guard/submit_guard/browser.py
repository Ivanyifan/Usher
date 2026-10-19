"""A browser for a guarded run: an installed Chrome or Edge (or Playwright's own Chromium), a fresh temporary
profile every run, service workers blocked, no downloads, no login.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable, Mapping

BROWSER_ENV = "SUBMIT_GUARD_BROWSER"
CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)
VIEWPORT = {"width": 1280, "height": 900}


def browser_executable(environ: Mapping[str, str] | None = None,
                       exists: Callable[[str], bool] = lambda path: Path(path).is_file()) -> str | None:
    """SUBMIT_GUARD_BROWSER, then Chrome, then Edge; None means Playwright's bundled Chromium."""
    environ = os.environ if environ is None else environ
    for candidate in (environ.get(BROWSER_ENV), *CANDIDATES):
        if candidate and exists(candidate):
            return candidate
    return None


class GuardedBrowser:
    """A persistent context on a temporary profile; close() also deletes the profile."""

    def __init__(self, playwright, *, headless: bool):
        self.profile_dir = Path(tempfile.mkdtemp(prefix="submit-guard-profile-"))
        executable = browser_executable()
        try:
            self.context = playwright.chromium.launch_persistent_context(
                str(self.profile_dir), headless=headless, service_workers="block", accept_downloads=False,
                viewport=VIEWPORT, **({"executable_path": executable} if executable else {}))
        except Exception:
            shutil.rmtree(self.profile_dir, ignore_errors=True)
            raise

    def close(self) -> None:
        try:
            self.context.close()
        finally:
            shutil.rmtree(self.profile_dir, ignore_errors=True)
