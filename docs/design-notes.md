# Design notes

## 1. Why one generic filler instead of adapters

A target list of new-grad roles is spread across several common applicant-tracking systems. An adapter per site costs maintenance that grows with every site and every redesign. The generic filler only understands controls, not sites. The trade-off is one model call per page and the risk of a wrong mapping, which is why the model never touches values and every unmatched field is reported to the user.

## 2. The model classifies, the program fills

The model returns a profile key, never an option index and never a value. That keeps personal data local, keeps the output small enough to validate strictly, and means a wrong mapping can only put one of your real values in the wrong place, never a guess; every field that doesn't match is listed in the report for you to check. For location, school and major, matching the value against a long option list needs the value itself, so two models choose independently and the program clicks only when they agree.

## 3. Blocking submit in code, not in a prompt

"Don't click Submit" in a prompt is not a safety property. Usher has four independent layers, and each one blocks the submit paths we have mapped on its own (the gaps we know of are listed with the guard package):

- **In-page guard**, injected into every frame before the page loads, blocks form submission events.
- **Network guard** on the browser context (so it covers iframes and popups) blocks submit-like requests. Service workers are disabled so nothing bypasses it.
- **Click guard** treats any button without an explicit type as a submit button. Blocking too much is the safe failure.
- **Keyboard guard**: every key press goes through an allow-list. Enter is never pressed on an application page.

Before the first action, a self-check proves the guards are live: every frame with form controls must carry the guard flag, and a test POST from a blank page must be caught. If not, nothing is filled.

The guards work with Playwright-driven Chrome (Chromium). They are not the only code-level guard of this kind: [playwright-write-guard](https://github.com/SandeepTakasi/playwright-write-guard) (Node, MIT, first published on npm on 2026-10-10) blocks every request that is not GET, HEAD or OPTIONS at the network layer and, inside the page, refuses clicks, form submits and Enter or Space presses on controls whose labels match its verb list (Save, Delete, Send, Pay and the like); its README says: "It is a safety net, not a security boundary." Usher's guards are written in Python, treat a button with no explicit type as a submit button, and refuse to run until the startup self-check passes.

## 4. Outcomes by rules, not by a model

An early version classified emails with a model. Usher now uses fixed rules on headers. They are explainable, free, and no email content leaves the machine.
