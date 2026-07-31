#!/usr/bin/env python3
"""Fast, offline checks for Fractile-specific routing rules."""
import monitor as m
import linkedin as li

def post(text, urls=None):
    return {"id": "1", "text": text, "entities": {"urls": [
        {"expanded_url": url} for url in (urls or [])]}}

def linkedin_post(text):
    return {"id": "1", "content": text, "author": {"type": "profile", "name": "Tester"}}

CASES = [
    ("company domain", post("Read this", ["https://fractile.ai/news"]), "accept"),
    ("founder", post("Walter Goodwin discussed Fractile's new processor"), "accept"),
    ("hardware context", post("Fractile memory compute accelerator cuts inference latency"), "accept"),
    ("statistics", post("Calculate the 90th fractile of the distribution"), "reject"),
    ("ambiguous", post("New Fractile announcement"), "maybe"),
]

for label, item, expected in CASES:
    actual, _ = m.structural(item)
    assert actual == expected, f"{label}: got {actual}, expected {expected}"

actual, _ = li.structural_li(linkedin_post("Fractile processors interleave memory and compute for AI inference"))
assert actual == "accept", actual
actual, _ = li.structural_li(linkedin_post("The empirical fractile of this distribution is 0.9"))
assert actual == "reject", actual
print("Fractile profile checks passed")
