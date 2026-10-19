"""The only place in submit_guard that clicks.

Refused: anything whose real type is submit (a <button> without a type attribute is a submit button), submit
and image inputs, reset inputs and buttons, links with an href, and button-like elements (button, input button,
role=button) whose accessible name or text contains a word from SUBMIT_BUTTON_WORDS. Options, checkboxes, radio
buttons and their labels are exempt from the word check, so an option called "Apply now" can still be chosen.

A click lands on more than the element: it bubbles to the ancestors (a span inside a submit button submits),
the point clicked may be a descendant, and a label forwards it to its control. So the checks run on the element,
every ancestor (across shadow roots), every descendant, and the control of the element or of any label among
its ancestors. More than MAX_DESCENDANTS descendants is refused outright.
"""
from __future__ import annotations

from submit_guard.words import SUBMIT_BUTTON_WORDS
from submit_guard.words import contains_substring

MAX_DESCENDANTS = 500

_INSPECT_JS = """(el) => {
  const info = (n) => {
    const tag = n.tagName.toLowerCase();
    const role = (n.getAttribute('role') || '').toLowerCase();
    const type = (tag === 'button' || tag === 'input') ? (n.type || '').toLowerCase() : '';
    let labelsChoice = false;
    if (tag === 'label') {
      const c = n.control || n.querySelector('input');
      labelsChoice = !!c && ['checkbox', 'radio'].includes((c.type || '').toLowerCase());
    }
    // The name only matters for button-like nodes; reading innerText of every ancestor (body included) is slow.
    const buttonLike = tag === 'button' || (tag === 'input' && type === 'button') || role === 'button';
    let name = '';
    if (buttonLike) {
      name = n.getAttribute('aria-label') || '';
      const ids = (n.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
      if (!name && ids.length) {
        name = ids.map((id) => { const m = n.ownerDocument.getElementById(id); return m ? m.textContent : ''; })
          .join(' ');
      }
      if (!name) name = (n.innerText || n.textContent || '');
      if (!name && tag === 'input') name = n.value || n.getAttribute('alt') || '';
      if (!name) name = n.getAttribute('title') || '';
    }
    return {tag, role, type, href: tag === 'a' && n.hasAttribute('href'), labelsChoice,
            name: name.replace(/\\s+/g, ' ').trim().slice(0, 200)};
  };
  const parentOf = (n) => {
    if (n.parentElement) return n.parentElement;
    const root = n.getRootNode();
    return root && root.host ? root.host : null;
  };
  const ancestors = [];
  for (let n = parentOf(el); n; n = parentOf(n)) ancestors.push(n);
  const all = el.querySelectorAll('*');
  const descendants = Array.from(all).slice(0, %d);
  const controls = [];
  for (const n of [el, ...ancestors]) {
    if (n.tagName.toLowerCase() === 'label' && n.control && n.control !== el) controls.push(n.control);
  }
  return {self: info(el), ancestors: ancestors.map(info), descendants: descendants.map(info),
          controls: controls.map(info), overflow: all.length > %d};
}""" % (MAX_DESCENDANTS, MAX_DESCENDANTS)


class ForbiddenClick(ValueError):
    """An element the agent must never click."""


def refusal(info: dict) -> str | None:
    """Why this one element may not be clicked, or None."""
    tag, role, kind = info.get("tag"), info.get("role"), info.get("type")
    if tag == "button" and kind in ("submit", "reset"):
        return f"button_type_{kind}"
    if tag == "input" and kind in ("submit", "image", "reset"):
        return f"input_type_{kind}"
    if info.get("href"):
        return "link_with_href"
    exempt = role == "option" or (tag == "input" and kind in ("checkbox", "radio")) or info.get("labelsChoice")
    button_like = tag == "button" or (tag == "input" and kind == "button") or role == "button"
    if button_like and not exempt and contains_substring(info.get("name"), SUBMIT_BUTTON_WORDS):
        return "submit_word_in_name"
    return None


def tree_refusal(tree: dict) -> str | None:
    """Why the click may not happen, looking at the element, its ancestors, descendants and label controls.
    The reason is prefixed with where it was found, e.g. "ancestor:button_type_submit"."""
    if tree.get("overflow"):
        return "too_many_descendants"
    reason = refusal(tree["self"])
    if reason:
        return reason
    for where in ("ancestors", "descendants", "controls"):
        for info in tree.get(where, ()):
            reason = refusal(info)
            if reason:
                return f"{where[:-1]}:{reason}"
    return None


class ClickGuard:
    # Named safe_click, not click, so a code search for .click( in submit_guard finds only this module.
    def safe_click(self, target, *, timeout: float | None = None) -> None:
        """target: a Playwright Locator for exactly one element, or an ElementHandle (the dropdown executor passes
        the handle of the one option in its control's scope). Either is inspected the same way before the click."""
        reason = tree_refusal(target.evaluate(_INSPECT_JS))
        if reason:
            raise ForbiddenClick(reason)
        target.click(**({"timeout": timeout} if timeout is not None else {}))
