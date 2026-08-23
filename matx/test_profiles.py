#!/usr/bin/env python3
"""Fast, offline checks for MatX-specific routing rules."""
import monitor as m
import linkedin as li

def post(text, urls=None, author=None):
    return {"id": "1", "text": text, "author": {"userName": author or "someone"},
            "entities": {"urls": [{"expanded_url": url} for url in (urls or [])]}}

def linkedin_post(text):
    return {"id": "1", "content": text, "author": {"type": "profile", "name": "Tester"}}

CASES = [
    ("company domain", post("Read this", ["https://matx.com/research"]), "accept"),
    ("company account", post("We are hiring!", author="MatXComputing"), "accept"),
    ("founder", post("Reiner Pope introduced the MatX One chip"), "accept"),
    ("common-name founder is judged, not accepted",
     post("Mike Gunter takes the darts final on Sunday"), "maybe"),
    ("hardware context", post("MatX One uses SRAM and HBM for LLM inference"), "accept"),
    ("motherboard form factor", post("ASUS B550 mATX motherboard with DDR4"), "reject"),
    ("ambiguous", post("New MatX announcement"), "maybe"),
    ("handle-fragment reply resolves, never reviews blind",
     post("@alx @XMoney 100", author="matx_ba"), "fetch_x"),
]

for label, item, expected in CASES:
    actual, _ = m.structural(item)
    assert actual == expected, f"{label}: got {actual}, expected {expected}"

# Post-resolution routing: review is ONLY for a real link we could not read.
ROUTES = [
    ("resolved text naming the company is judged",
     m.route_resolved("MatX One taped out at TSMC", True), "judge"),
    ("unreadable real link goes to review", m.route_resolved(None, True), "review"),
    ("resolved text without the company is dropped",
     m.route_resolved("Marvell and Micron memory-compute roundup", True), "drop"),
    ("nothing to read at all is dropped", m.route_resolved(None, False), "drop"),
]
for label, actual, expected in ROUTES:
    assert actual == expected, f"{label}: got {actual}, expected {expected}"

actual, _ = li.structural_li(linkedin_post("MatX One supports LLM training and inference with SRAM and HBM"))
assert actual == "accept", actual
actual, _ = li.structural_li(linkedin_post("Max is retiring after thirty years of practicing law"))
assert actual == "reject", actual
print("MatX profile checks passed")
