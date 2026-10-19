"""How to let through a write that a page makes while it is filled. The hosts and names here are made up.

Keep each rule as narrow as the page allows: one method, one host, an exact path, and for GraphQL the exact
operation names. A write that looks like a submission (its path or operationName contains a word from
SUBMIT_REQUEST_WORDS, a GraphQL write whose operationName cannot be read, or a write to the page's own address)
is aborted and stops the run whatever rule it matches.
"""
from submit_guard import AllowRule, GuardStack, NetworkGuard

RULES = (
    # A file upload: the form POSTs the file to the root of a storage bucket.
    AllowRule("POST", "uploads.example.test", "/", path_exact=True),
    # A page that saves each field as it is filled and suggests locations while you type.
    AllowRule("POST", "forms.example.test", "/api/public-graphql",
              operation_names=frozenset({"SaveFieldValue", "SuggestLocation"}), path_exact=True),
)


def guarded(context) -> GuardStack:
    return GuardStack(context, network_guard=NetworkGuard(RULES))
