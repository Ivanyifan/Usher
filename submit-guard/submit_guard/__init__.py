"""Code-level guards that keep a Playwright-driven Chrome from submitting a form.

Nothing in your agent should press a key, type or click except through KeyGuard and ClickGuard; PageGuard and
NetworkGuard stop any submission that slips through anyway. GuardStack runs them in order.
"""
from submit_guard.click import ClickGuard, ForbiddenClick
from submit_guard.events import AllowedRequest, BlockedRequest, BlockEvent
from submit_guard.keyboard import ForbiddenKey, KeyGuard
from submit_guard.network import AllowRule, NetworkGuard
from submit_guard.page import NavigationWatch, PageGuard
from submit_guard.stack import GuardStack, SubmitBlocked

__all__ = ["AllowRule", "AllowedRequest", "BlockEvent", "BlockedRequest", "ClickGuard", "ForbiddenClick", "ForbiddenKey", "GuardStack",
           "KeyGuard", "NavigationWatch", "NetworkGuard", "PageGuard", "SubmitBlocked"]
