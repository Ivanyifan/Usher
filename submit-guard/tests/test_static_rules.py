"""Static rules for submit_guard: only keyboard.py sends keys, types or clears; only click.py clicks; nothing
dispatches synthetic events; only Playwright and the standard library are imported."""
import ast
from pathlib import Path
import sys

PACKAGE = Path(__file__).resolve().parents[1] / "submit_guard"
KEY_CALLS = {"press", "press_sequentially", "type", "clear", "keyboard"}
CLICK_CALLS = {"click", "dblclick", "tap", "mouse", "touchscreen"}


def _sources():
    files = sorted(PACKAGE.rglob("*.py"))
    assert files, "no sources found"
    return [(path.relative_to(PACKAGE).as_posix(), ast.parse(path.read_text(encoding="utf-8"))) for path in files]


def _attributes(names, allowed_in):
    return [(rel, node.attr, node.lineno) for rel, tree in _sources() for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in names and rel != allowed_in]


def test_keys_and_typing_only_in_the_keyboard_guard():
    assert _attributes(KEY_CALLS, "keyboard.py") == []


def test_clicks_only_in_the_click_guard():
    assert _attributes(CLICK_CALLS, "click.py") == []


def test_no_dispatch_event_anywhere():
    assert _attributes({"dispatch_event"}, None) == []


def test_only_playwright_and_the_standard_library():
    offenders = []
    for rel, tree in _sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top not in sys.stdlib_module_names and top not in ("submit_guard", "playwright", "__future__"):
                    offenders.append((rel, name))
    assert offenders == []
