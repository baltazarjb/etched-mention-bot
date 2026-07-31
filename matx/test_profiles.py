#!/usr/bin/env python3
"""Fast, offline checks for MatX-specific routing rules."""
import monitor as m
import linkedin as li

def post(text, urls=None):
    return {"id": "1", "text": text, "entities": {"urls": [
        {"expanded_url": url} for url in (urls or [])]}}

def linkedin_post(text):
    return {"id": "1", "content": text, "author": {"type": "profile", "name": "Tester"}}

CASES = [
    ("company domain", post("Read this", ["https://matx.com/research"]), "accept"),
    ("founder", post("Reiner Pope introduced the MatX One chip"), "accept"),
    ("hardware context", post("MatX One uses SRAM and HBM for LLM inference"), "accept"),
    ("motherboard form factor", post("ASUS B550 mATX motherboard with DDR4"), "reject"),
    ("ambiguous", post("New MatX announcement"), "maybe"),
]

for label, item, expected in CASES:
    actual, _ = m.structural(item)
    assert actual == expected, f"{label}: got {actual}, expected {expected}"

actual, _ = li.structural_li(linkedin_post("MatX One supports LLM training and inference with SRAM and HBM"))
assert actual == "accept", actual
print("MatX profile checks passed")
