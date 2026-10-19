"""Key guard: Enter is never sent, text goes only into text inputs; fixture pages only."""
import pytest

from submit_guard.keyboard import ALLOWED_KEYS, ForbiddenKey, KeyGuard, check_key, check_text
from tests.support import browser, other_server, page, playwright_instance, server  # noqa: F401


@pytest.mark.parametrize("key", ["Enter", "NumpadEnter", "Shift+Enter", "Control+Enter", "Alt+NumpadEnter",
                                 "a", "Space", "F5", "Control+a", "Delete", ""])
def test_keys_outside_the_allow_list_are_refused(key):
    with pytest.raises(ForbiddenKey):
        check_key(key)


@pytest.mark.parametrize("key", sorted(ALLOWED_KEYS))
def test_allowed_keys_pass(key):
    check_key(key)
    assert "Enter" not in key


@pytest.mark.parametrize("text", ["line\nbreak", "carriage\rreturn", "tab\there", "nul\x00", "bell\x07",
                                  "zero" + chr(0x200B) + "width", "escape\x1b", "line" + chr(0x2028) + "sep",
                                  "para" + chr(0x2029) + "sep"])
def test_control_characters_are_refused(text):
    with pytest.raises(ForbiddenKey):
        check_text(text)


@pytest.mark.parametrize("text", ["Fixture Person", "fixture@example.invalid", "+1 555 0100", "测试", ""])
def test_printable_text_passes(text):
    check_text(text)


def test_clearing_only_text_fields(page, server):
    page.goto(server.url("form.html"))
    keys = KeyGuard()
    page.locator("#name").fill("Fixture")
    keys.clear_text(page.locator("#name"))
    assert page.locator("#name").input_value() == ""
    page.locator("#cb").check()
    for selector in ("#cb", "#r1", "#typesubmit", "#rolecombo"):
        with pytest.raises(ForbiddenKey):
            keys.clear_text(page.locator(selector))
    assert page.locator("#cb").is_checked()
    assert server.writes == 0


def test_typing_into_buttons_and_checkboxes_is_refused_and_enter_never_reaches_the_page(page, server):
    page.goto(server.url("form.html"))
    keys = KeyGuard()
    keys.type_text(page.locator("#name"), "Fixture Person")
    keys.type_text(page.locator("#notes"), "plain words")
    assert page.locator("#name").input_value() == "Fixture Person"
    page.evaluate("window.__keydowns = 0")
    for selector in ("#typesubmit", "#plain", "#inputsubmit", "#cb", "#r1", "#rolebutton", "#rolecombo"):
        with pytest.raises(ForbiddenKey):
            keys.type_text(page.locator(selector), "x")
    for key in ("Enter", "NumpadEnter", "Shift+Enter"):
        with pytest.raises(ForbiddenKey):
            keys.send_key(page.locator("#name"), key)
        with pytest.raises(ForbiddenKey):
            keys.send_key(page, key)
    with pytest.raises(ForbiddenKey):
        keys.type_text(page.locator("#name"), "two\nlines")
    keys.send_key(page.locator("#name"), "Tab")
    # No page guard is installed here: the wrapper alone kept every Enter off the page.
    assert page.evaluate("window.__keydowns") == 1  # the one Tab
    assert server.writes == 0 and page.url == server.url("form.html")
