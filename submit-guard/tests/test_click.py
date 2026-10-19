"""Click guard: submit-type elements, submit-like names and links are never clicked."""
import pytest

from submit_guard.click import ClickGuard, ForbiddenClick, refusal, tree_refusal
from tests.support import browser, no_navigation, other_server, page, playwright_instance, \
    server  # noqa: F401


@pytest.mark.parametrize("info, reason", [
    ({"tag": "button", "type": "submit", "name": "Continue"}, "button_type_submit"),
    ({"tag": "button", "type": "reset", "name": "Clear"}, "button_type_reset"),
    ({"tag": "input", "type": "submit", "name": "Go"}, "input_type_submit"),
    ({"tag": "input", "type": "image", "name": "Go"}, "input_type_image"),
    ({"tag": "a", "type": "", "href": True, "name": "Privacy"}, "link_with_href"),
    ({"tag": "div", "role": "button", "type": "", "name": "Submit application"}, "submit_word_in_name"),
    ({"tag": "button", "type": "button", "name": "Apply now"}, "submit_word_in_name"),
    ({"tag": "input", "type": "button", "name": "Send"}, "submit_word_in_name"),
    ({"tag": "span", "role": "button", "type": "", "name": "SUBMIT"}, "submit_word_in_name"),
])
def test_refusals(info, reason):
    assert refusal(info) == reason


@pytest.mark.parametrize("info", [
    {"tag": "div", "role": "option", "type": "", "name": "Apply via referral"},
    {"tag": "input", "type": "checkbox", "name": "Apply to all"},
    {"tag": "input", "type": "radio", "name": "Send updates"},
    {"tag": "label", "type": "", "labelsChoice": True, "name": "Apply to all locations"},
    {"tag": "button", "type": "button", "name": "Attach"},
    {"tag": "div", "role": "combobox", "type": "", "name": "Country"},
])
def test_allowed(info):
    assert refusal(info) is None


SPAN = {"tag": "span", "role": "", "type": "", "name": "Next"}


@pytest.mark.parametrize("tree, reason", [
    ({"self": SPAN, "ancestors": [{"tag": "button", "type": "submit", "name": "Next"}]},
     "ancestor:button_type_submit"),
    ({"self": SPAN, "ancestors": [{"tag": "a", "type": "", "href": True, "name": "More"}]},
     "ancestor:link_with_href"),
    ({"self": {"tag": "div", "type": "", "name": "Go"}, "descendants": [{"tag": "input", "type": "submit"}]},
     "descendant:input_type_submit"),
    ({"self": {"tag": "label", "type": "", "name": "Go on"}, "controls": [{"tag": "button", "type": "submit"}]},
     "control:button_type_submit"),
    ({"self": SPAN, "ancestors": [{"tag": "div", "role": "button", "type": "", "name": "Send it"}]},
     "ancestor:submit_word_in_name"),
    ({"self": SPAN, "overflow": True}, "too_many_descendants"),
])
def test_tree_refusals(tree, reason):
    assert tree_refusal(tree) == reason


def test_tree_allows_a_plain_option():
    assert tree_refusal({"self": {"tag": "div", "role": "option", "type": "", "name": "Apply via referral"},
                         "ancestors": [{"tag": "div", "role": "listbox", "type": "", "name": "x"},
                                       {"tag": "form", "type": "", "name": "x"}],
                         "descendants": [], "controls": []}) is None


@pytest.mark.parametrize("selector", ["#plain", "#typesubmit", "#inputsubmit", "#inputimage", "#resetbtn",
                                      "#rolebutton", "#link", "#innerspan", "#labelforsubmit", "#wrapsubmit",
                                      "#spaninlink", "#spaninlabel"])
def test_refused_on_the_page(page, server, selector):
    page.goto(server.url("form.html"))
    navigations = no_navigation(page)
    with pytest.raises(ForbiddenClick):
        ClickGuard().safe_click(page.locator(selector))
    page.wait_for_timeout(200)
    assert server.writes == 0 and navigations == [] and page.url == server.url("form.html")


def test_options_choice_labels_and_attach_are_clicked(page, server):
    page.goto(server.url("form.html"))
    navigations = no_navigation(page)
    clicks = ClickGuard()
    clicks.safe_click(page.locator("#opt"))
    clicks.safe_click(page.locator("#cblabel"))
    clicks.safe_click(page.locator("#rlabel"))
    clicks.safe_click(page.locator("#attach"))
    assert page.evaluate("window.__optionClicked") is True
    assert page.locator("#cb").is_checked() and page.locator("#r1").is_checked()
    assert server.writes == 0 and navigations == []
