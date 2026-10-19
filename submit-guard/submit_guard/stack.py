"""The guards in the order a run uses them.

1. Before the first goto: the in-page guard (init script).
2. goto and waiting only; nothing is clicked or typed.
3. After the page has loaded and before the first action: the network guard, the navigation watch, then the
   self-check. The self-check fails (selfcheck() returns False; fill nothing) unless every
   frame with form controls has the guard flag on and a POST sent from a fresh about:blank page in the same
   context to SELFTEST_HOST is caught by the network guard. The test page is not the application page, whose
   CSP could stop the request first and make the check pass for the wrong reason.
4. After every action: check() reads the in-page records, the network guard's submit-like blocks and the
   navigation watch; anything there raises SubmitBlocked and the run stops.
5. hand_over(): every guard comes off before the person gets the page.
"""
from __future__ import annotations

from submit_guard.network import SELFTEST_HOST, NetworkGuard
from submit_guard.page import NavigationWatch, PageGuard
from submit_guard.events import BlockEvent

FORM_CONTROLS = "input, select, textarea, [role=combobox], [contenteditable=true]"
_SELFTEST_JS = """async (url) => {
  try { await fetch(url, {method: 'POST', body: 'selftest', mode: 'no-cors'}); } catch (e) { }
  return true;
}"""


class SubmitBlocked(RuntimeError):
    def __init__(self, events: list[BlockEvent]):
        self.events = events
        super().__init__(f"{len(events)} submission(s) blocked: " + ", ".join(e.layer for e in events))


class GuardStack:
    def __init__(self, context, network_guard: NetworkGuard | None = None, page_guard: PageGuard | None = None):
        self.context = context
        self.page_guard = page_guard or PageGuard()
        self.network_guard = network_guard or NetworkGuard()
        self.navigation: NavigationWatch | None = None
        self._network_on = False

    def before_goto(self) -> None:
        self.page_guard.install(self.context)

    def after_load(self, page, form_frame=None) -> None:
        """A write to the page's own address or the form frame's (host and path) counts as submit-like."""
        urls = [page.main_frame.url] + ([form_frame.url] if form_frame is not None else [])
        self.network_guard.install(self.context, urls)
        self._network_on = True
        self.navigation = NavigationWatch(page, form_frame)

    def selfcheck(self, page) -> bool:
        for frame in page.frames:
            try:
                has_controls = frame.locator(FORM_CONTROLS).count() > 0
            except Exception:
                continue
            if has_controls and not self.page_guard.active_in(frame):
                return False
        if not self._network_on:
            return False
        before = self.network_guard.selftest_hits
        probe = self.context.new_page()
        try:
            probe.evaluate(_SELFTEST_JS, f"https://{SELFTEST_HOST}/")
        finally:
            probe.close()
        return self.network_guard.selftest_hits > before

    def check(self) -> None:
        events = self.page_guard.drain() + self.network_guard.drain()
        if self.navigation is not None:
            events += self.navigation.drain()
        if events:
            raise SubmitBlocked(events)

    def quiet_blocks(self) -> int:
        """The network guard's count of blocked writes that were not submit-like (read-only)."""
        return self.network_guard.quiet_blocks()

    # The network guard's read-only counts of let-through writes, for a caller that uploads files.
    def write_failures(self) -> int:
        return self.network_guard.write_failures()

    def allowed_writes(self) -> int:
        return self.network_guard.allowed_writes()

    def pending_since(self, seq: int) -> int:
        return self.network_guard.pending_since(seq)

    def hand_over(self) -> None:
        if self.navigation is not None:
            self.navigation.stop()
            self.navigation = None
        self.network_guard.remove()
        self._network_on = False
        self.page_guard.remove()
