#!/usr/bin/env python3
"""Fast, offline checks for Fractile-specific routing rules."""
import monitor as m
import linkedin as li

def post(text, urls=None, author=None):
    return {"id": "1", "text": text, "author": {"userName": author or "someone"},
            "entities": {"urls": [{"expanded_url": url} for url in (urls or [])]}}

def linkedin_post(text):
    return {"id": "1", "content": text, "author": {"type": "profile", "name": "Tester"}}

CASES = [
    ("company domain", post("Read this", ["https://fractile.ai/news"]), "accept"),
    ("founder", post("Walter Goodwin discussed Fractile's new processor"), "accept"),
    ("common-name founder is judged, not accepted",
     post("Pete Hughes chipped in from the fairway"), "maybe"),
    ("hardware context", post("Fractile memory compute accelerator cuts inference latency"), "accept"),
    ("statistics", post("Calculate the 90th fractile of the distribution"), "reject"),
    ("ambiguous", post("New Fractile announcement"), "maybe"),
    ("no visible signal resolves, never reviews blind",
     post("Great writeup on the Marvell warrant"), "fetch_x"),
]

for label, item, expected in CASES:
    actual, _ = m.structural(item)
    assert actual == expected, f"{label}: got {actual}, expected {expected}"

# Post-resolution routing: review is ONLY for a real link we could not read.
ROUTES = [
    ("resolved text naming the company is judged",
     m.route_resolved("Fractile raises for compute-in-memory chips", True), "judge"),
    ("unreadable real link goes to review", m.route_resolved(None, True), "review"),
    ("resolved text without the company is dropped",
     m.route_resolved("Micron opens a $10B memory research lab", True), "drop"),
    ("nothing to read at all is dropped", m.route_resolved(None, False), "drop"),
]
for label, actual, expected in ROUTES:
    assert actual == expected, f"{label}: got {actual}, expected {expected}"

actual, _ = li.structural_li(linkedin_post("Fractile processors interleave memory and compute for AI inference"))
assert actual == "accept", actual
actual, _ = li.structural_li(linkedin_post("The empirical fractile of this distribution is 0.9"))
assert actual == "reject", actual
print("Fractile profile checks passed")
