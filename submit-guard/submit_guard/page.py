"""In-page guard and navigation watch.

While the window flag is on, every frame swallows submit events, Enter (keydown, keypress, keyup) and calls to
HTMLFormElement.prototype.submit and requestSubmit, and records each one. It is installed as a context init
script before the page loads (so new frames and documents get it) and evaluated into frames already loaded.
remove() disposes of the init script and switches every frame back off, so a reload, a new page or a new
iframe after the hand-over carries no guard and the person's own Submit goes through. drain() and remove() before
install() do nothing.
"""
from __future__ import annotations

from submit_guard.events import BlockEvent

GUARD_JS = r"""(() => {
  if (window.__submitGuardInstalled) { return; }
  window.__submitGuardInstalled = true;
  window.__submitGuardGuard = true;
  window.__submitGuardBlocked = [];
  const record = (layer) => {
    if (window.__submitGuardBlocked.length < 200) { window.__submitGuardBlocked.push(layer); }
  };
  const isEnter = (e) => e.key === 'Enter' || e.code === 'Enter' || e.code === 'NumpadEnter'
    || e.keyCode === 13 || e.which === 13;
  const onSubmit = (e) => {
    if (!window.__submitGuardGuard) { return; }
    e.preventDefault(); e.stopImmediatePropagation(); record('page_submit');
  };
  const onKey = (e) => {
    if (!window.__submitGuardGuard || !isEnter(e)) { return; }
    e.preventDefault(); e.stopImmediatePropagation();
    if (e.type === 'keydown') { record('page_enter'); }
  };
  window.addEventListener('submit', onSubmit, true);
  const keyEvents = ['keydown', 'keypress', 'keyup'];
  for (const name of keyEvents) { window.addEventListener(name, onKey, true); }
  const proto = HTMLFormElement.prototype;
  const originalSubmit = proto.submit;
  const originalRequestSubmit = proto.requestSubmit;
  proto.submit = function () {
    if (window.__submitGuardGuard) { record('form_submit_call'); return undefined; }
    return originalSubmit.apply(this, arguments);
  };
  proto.requestSubmit = function () {
    if (window.__submitGuardGuard) { record('form_submit_call'); return undefined; }
    return originalRequestSubmit.apply(this, arguments);
  };
  window.__submitGuardRemove = () => {
    window.__submitGuardGuard = false;
    window.__submitGuardInstalled = false;
    window.removeEventListener('submit', onSubmit, true);
    for (const name of keyEvents) { window.removeEventListener(name, onKey, true); }
    proto.submit = originalSubmit;
    proto.requestSubmit = originalRequestSubmit;
  };
})()"""

_DRAIN_JS = """() => {
  const blocked = Array.isArray(window.__submitGuardBlocked) ? window.__submitGuardBlocked : [];
  window.__submitGuardBlocked = [];
  return blocked;
}"""
_ACTIVE_JS = "() => window.__submitGuardGuard === true"
_REMOVE_JS = "() => { if (typeof window.__submitGuardRemove === 'function') { window.__submitGuardRemove(); } }"
_LAYERS = ("page_submit", "page_enter", "form_submit_call")


def _frames(context):
    if context is None:
        return
    for page in context.pages:
        for frame in page.frames:
            yield frame


class PageGuard:
    def __init__(self):
        self._context = None
        self._script = None

    def install(self, context) -> None:
        """Before the first goto: every document in the context gets the guard. Also covers frames already
        loaded (a guard installed late)."""
        self._context = context
        self._script = context.add_init_script(GUARD_JS)
        if self._script is None:  # before Playwright 1.60 the script could not be removed at hand-over
            raise RuntimeError("submit_guard needs Playwright 1.60 or later; close this browser context, its guard "
                               "cannot be removed and would swallow the person's own Submit")
        for frame in _frames(context):
            try:
                frame.evaluate(GUARD_JS)
            except Exception:  # a frame that is detaching; the init script covers its replacement
                pass

    def active_in(self, frame) -> bool:
        try:
            return bool(frame.evaluate(_ACTIVE_JS))
        except Exception:
            return False

    def drain(self) -> list[BlockEvent]:
        events = []
        for frame in _frames(self._context):
            try:
                layers = frame.evaluate(_DRAIN_JS)
            except Exception:
                continue
            events += [BlockEvent(layer=layer) for layer in layers if layer in _LAYERS]
        return events

    def remove(self) -> None:
        """Hand-over: dispose of the init script first, then switch every live frame off."""
        if self._script is not None:
            self._script.dispose()
            self._script = None
        for frame in _frames(self._context):
            try:
                frame.evaluate(_REMOVE_JS)
            except Exception:
                pass


class NavigationWatch:
    """After the guards are up, any navigation of the main frame or the form's frame (same-document URL changes
    included) counts as a blocked submission."""

    def __init__(self, page, form_frame=None):
        self._page = page
        self._watched = {page.main_frame} | ({form_frame} if form_frame is not None else set())
        self._urls = {frame: frame.url for frame in self._watched}
        self._events: list[BlockEvent] = []
        self._handler = self._on_navigated
        page.on("framenavigated", self._handler)

    def _on_navigated(self, frame) -> None:
        if frame in self._watched:
            self._events.append(BlockEvent(layer="navigation"))

    def drain(self) -> list[BlockEvent]:
        events, self._events = self._events, []
        for frame in self._watched:
            if not events and frame.url != self._urls[frame]:
                events.append(BlockEvent(layer="navigation"))
            self._urls[frame] = frame.url
        return events

    def stop(self) -> None:
        self._page.remove_listener("framenavigated", self._handler)
