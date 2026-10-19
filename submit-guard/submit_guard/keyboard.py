"""The only place in submit_guard that sends keys, types text or clears a text field.

Enter and NumpadEnter are never sent, alone or in a combination: inside a form they submit it. Keys outside
ALLOWED_KEYS are refused too. Text is typed only into inputs whose real type is text-like (a typeable combobox
is such an input; role=combobox alone is not enough) and textareas, and only printable characters: a newline
typed character by character is an Enter, and typing a space into a focused button presses it.
"""
from __future__ import annotations

import unicodedata

ALLOWED_KEYS = frozenset({"ArrowDown", "ArrowUp", "Escape", "Tab", "Backspace"})
FORBIDDEN_TOKENS = frozenset({"Enter", "NumpadEnter"})
TEXT_INPUT_TYPES = frozenset({"text", "email", "tel", "url", "search", "number"})

_TARGET_JS = """(el) => ({
  tag: el.tagName.toLowerCase(),
  type: el.tagName.toLowerCase() === 'input' ? (el.type || 'text').toLowerCase() : null,
  role: (el.getAttribute('role') || '').toLowerCase(),
  disabled: !!el.disabled,
  readOnly: !!el.readOnly,
})"""


class ForbiddenKey(ValueError):
    """A key, a character or a target the agent must never type into."""


def check_key(key: str) -> None:
    parts = key.split("+")
    if any(part in FORBIDDEN_TOKENS for part in parts):
        raise ForbiddenKey(f"key {key!r} contains Enter")
    if key not in ALLOWED_KEYS:
        raise ForbiddenKey(f"key {key!r} is not on the allow list")


def check_text(text: str) -> None:
    for char in text:
        # Cc covers newline, carriage return and tab; Cf, Cs, Co and Cn are refused as well, and so are the line
        # and paragraph separators U+2028 and U+2029 (Zl, Zp).
        category = unicodedata.category(char)
        if category.startswith("C") or category in ("Zl", "Zp"):
            raise ForbiddenKey(f"text contains a control or separator character U+{ord(char):04X}")


def check_target(info: dict) -> None:
    tag, kind = info.get("tag"), info.get("type")
    if info.get("disabled") or info.get("readOnly"):
        raise ForbiddenKey("target is disabled or read-only")
    if tag == "textarea":
        return
    if tag == "input" and kind in TEXT_INPUT_TYPES:
        return
    raise ForbiddenKey(f"text goes only into text-like inputs and textareas, not {tag}/{kind}")


class KeyGuard:
    # Named send_key, not press, so a code search for .press( in submit_guard finds only this module.
    def send_key(self, target, key: str) -> None:
        """target: a Playwright Locator (key goes to that element) or a Page (key goes to the focused element)."""
        check_key(key)
        if hasattr(target, "keyboard"):
            target.keyboard.press(key)
        else:
            target.press(key)

    def type_text(self, target, text: str) -> None:
        """target: a Playwright Locator for one text-like input (a typeable combobox included) or textarea."""
        check_text(text)
        check_target(target.evaluate(_TARGET_JS))
        target.press_sequentially(text)

    def clear_text(self, target) -> None:
        """Empties one text-like input or textarea (Locator.clear sets the value; no key is sent). Same target
        check as type_text: never a checkbox, button, read-only or disabled control."""
        check_target(target.evaluate(_TARGET_JS))
        target.clear()
