# submit-guard

**Code-level guards that keep a Playwright-driven Chrome from submitting a form.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

An agent that fills web forms should stop before Submit. Asking it nicely in a prompt is not enough: pages submit on Enter, on blur, on timers, from iframes, popups and service workers. This package enforces the stop in code. Four independent guards stop the submit paths listed below, a startup self-check refuses to run unless every guard is proven live, and the paths they do not cover are listed too. When the agent is done, `hand_over()` removes the guards so the person can review the page and press Submit themselves.

It works with Playwright-driven Chrome (Chromium), from Python.

## The four guards

| Guard | Where it acts | What it does |
|---|---|---|
| Keyboard | before each key the agent sends | refuses Enter and NumpadEnter, and any key outside a short allow list; types only into text inputs and textareas |
| Click | before each click the agent makes | refuses submit and reset buttons (a `<button>` with no type is a submit button), submit and image inputs, links, and buttons whose name contains submit, apply or send |
| Page | in every frame, installed before the page's own scripts run | swallows submit events and Enter, and turns `form.submit()` and `requestSubmit()` into no-ops; a navigation of the page after the guards are up is recorded |
| Network | `context.route` on the whole browser context, so iframes and popups too | aborts every request that is not GET, HEAD or OPTIONS unless the caller allows it; one that looks like a submission stops the run, and so does an allowed write answered with 307 or 308 |

Each guard works without the others. After every action, `check()` raises `SubmitBlocked` if any guard recorded a submission. The self-check refuses to start unless every frame with form controls has the page guard on and a test POST is caught by the network guard. `hand_over()` removes all four.

## Submit paths and tests

What the test suite in this repository shows today, measured, not intended. "Stopped" means nothing reached the server. "Detected" means the run stops but the request has already gone out.

| Submit path | Result | Guard | Tests |
|---|---|---|---|
| Enter in a text field (implicit submission) | stopped | keyboard; page if a raw Enter gets through | test_keyboard, test_page_guard, test_combined, challenge 1 |
| `<button>` with no type | stopped | click; page if a raw click gets through | test_click, test_page_guard, challenge 2 |
| `form.submit()` from a script (on blur) | stopped | page | test_page_guard, challenge 3 |
| `form.requestSubmit()` from a timer | stopped | page | test_page_guard, challenge 4 |
| A form inside an iframe, same or cross origin | stopped | page (every frame), network | test_page_guard, test_network_guard, challenge 5 |
| `fetch` POST | stopped | network | test_network_guard, challenge 6 |
| `navigator.sendBeacon` | stopped (aborted and listed; the run goes on unless the path looks like a submission) | network | test_network_guard, challenge 7 |
| A popup window that submits | stopped | page and network, both context-wide | test_network_guard, challenge 8 |
| A service worker that POSTs | stopped (service workers are blocked; with them allowed, the network guard still aborts the POST) | browser setting, network | test_network_guard, challenge 9 |
| A script that navigates (`location.href`, `history.pushState`) | detected | navigation watch | test_combined |
| Meta refresh to a confirm page | detected: the GET reaches the server | navigation watch | challenge 10 |
| 307/308 redirect of an allowed write | detected: the repeated request reaches the server | network | test_network_guard, test_challenge_guarded |

## Known gaps

Not covered, or not tested, today:

- **A navigation that carries data in a GET** (a meta refresh, `location.assign`, a link). The network guard lets GET through by design, so the request goes out; the navigation watch only stops the run afterwards. Challenge 10 shows it.
- **307/308 redirect of an allowed write: detected, not prevented.** Playwright's route sees only the first request, so when a server answers an allowed write with 307 or 308, the browser repeats it with the same method and body to the new address and the guard cannot stop that repeat. The network guard watches the status of every write it lets through and stops the run on a 307 or 308 (`network_redirect`). `tests/test_network_guard.py` and `tests/test_challenge_guarded.py` pin both halves: the run stops, and the repeated request still reaches the server. With no allow rules (the default) there is no allowed write to redirect.
- **A cross-origin 303 after an allowed write.** The response event sometimes misses the middle hop, so the write can be counted as 3xx, 4xx or no response. It is never counted as 2xx, so the count errs toward a failure.
- **A 2xx is not proof that a write was saved.** The guard reads only the status code, never the response body, and a GraphQL error usually comes back as 200 too.
- **XHR.** It goes through the same route as fetch, but there is no separate test.
- **A form with `method="get"`.** Its submit event goes through the page guard like any other, but there is no separate test.
- **WebSocket messages, `fetchLater`, requests sent during unload, SharedWorker.** Not tested.
- **Anything outside the guarded browser context**: other contexts, other HTTP clients, or code that removes the guards. The browser's own background traffic is outside the guards' view too: in our runs Chromium's network service contacted accounts.google.com, content-autofill.googleapis.com, android.clients.google.com, www.google.com and redirector.gvt1.com, and `context.route` never sees those requests.

The guards are a safety layer for an agent you run yourself. They are not a sandbox against hostile code.

## The ten-trap challenge

`challenge/` is a synthetic application page with ten hidden ways to submit, and a local server that counts every submission it receives. `tests/test_challenge_traps.py` proves that without guards, each trap really submits. `tests/test_challenge_guarded.py` runs each trap with the guards on and asserts what happens, including trap 10, which gets through.

`challenge/run_demo.py` records all ten traps on one page. A real run stops at the first block; the demo keeps going so every trap can be shown. The captions in the recording come from the demo script, not from the guards.

```
python -m challenge.server      # then open http://127.0.0.1:8765/
python -m challenge.run_demo    # records the guarded run to demo/demo.webm (and .mp4, .gif with ffmpeg)
```

## Use

```python
from playwright.sync_api import sync_playwright
from submit_guard import ClickGuard, GuardStack, KeyGuard, SubmitBlocked
from submit_guard.browser import GuardedBrowser

with sync_playwright() as p:
    browser = GuardedBrowser(p, headless=False)      # fresh profile, service workers blocked
    page = browser.context.new_page()
    guards = GuardStack(browser.context)
    guards.before_goto()                             # page guard, before the page's own scripts
    page.goto("https://example.test/apply")
    guards.after_load(page)                          # network guard and navigation watch
    if not guards.selfcheck(page):
        raise SystemExit("a guard is not live; nothing filled")
    keys, clicks = KeyGuard(), ClickGuard()
    keys.type_text(page.locator("#name"), "Jordan Example")
    guards.check()                                   # after every action; raises SubmitBlocked
    guards.hand_over()                               # the person reviews and presses Submit
```

To let a page's own background writes through (an upload, a field saved as you type), pass narrow `AllowRule`s; see `examples/allow_rules.py`. No rule lets through a write that looks like a submission. `allowed_requests()` lists every write a rule let through, counted by how it was answered.

Needs Python 3.10+ and Playwright 1.60+. Before 1.60, `add_init_script` returns no handle, so the page guard could not be removed at hand-over; `PageGuard.install()` raises instead of running with a guard it cannot take off.

## Prior art

[playwright-write-guard](https://github.com/SandeepTakasi/playwright-write-guard) (Node, MIT, first published on npm on 2026-10-10) blocks every request that is not GET, HEAD or OPTIONS at the network layer and, inside the page, refuses clicks, form submits and Enter or Space presses on controls whose labels match its verb list; its README says: "It is a safety net, not a security boundary." This package is written in Python, is aimed only at form submission, treats a button with no type as a submit button, and refuses to start until the self-check passes.

## License

MIT
