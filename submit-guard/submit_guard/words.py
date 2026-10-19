"""The word lists the click guard and the network guard use, and how they match."""
from __future__ import annotations

# A button-like element whose accessible name contains one of these is never clicked.
SUBMIT_BUTTON_WORDS = ("submit", "apply", "send")
# A blocked write request whose path or GraphQL operationName contains one of these stops the run.
SUBMIT_REQUEST_WORDS = ("apply", "application", "submit", "submission", "candidate", "job_app")


def contains_substring(text: str | None, words) -> str | None:
    """The first of `words` anywhere in `text`, case-insensitive; else None. For the fail-safe lists."""
    if not text:
        return None
    lowered = text.casefold()
    for word in words:
        if word.casefold() in lowered:
            return word
    return None
