#!/usr/bin/env python3
"""Summarize Ragnaros deck usage from the usage log.

Usage: python3 tools/usage_report.py [logpath]
"""
import json
import os
import sys
from collections import Counter

log = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
    "ragnaros", "usage.jsonl")

events = []
try:
    with open(log) as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
except FileNotFoundError:
    sys.exit(f"no usage log at {log} - use the deck first")

if not events:
    sys.exit("log is empty - use the deck first")

print(f"{len(events)} events logged\n")

keys = Counter()
knobs = Counter()
presses = Counter()
profiles = Counter()
for e in events:
    profiles[e["profile"]] += 1
    label = f"[{e['profile']}] {e['kind']} {e['idx']}"
    if e["kind"] == "key":
        action = (e.get("action") or "unmapped")[:48]
        keys[f"{label} -> {action}"] += 1
    elif e["kind"] == "knob":
        knobs[f"{label} {'cw' if e['value'] > 0 else 'ccw'}"] += 1
    elif e["kind"] == "knob_press":
        presses[label] += 1

print("== key presses ==")
for label, n in keys.most_common(20):
    print(f"{n:5d}  {label}")
print("\n== knob rotates ==")
for label, n in knobs.most_common(10):
    print(f"{n:5d}  {label}")
print("\n== knob presses ==")
for label, n in presses.most_common(10):
    print(f"{n:5d}  {label}")
print("\n== by profile ==")
for label, n in profiles.most_common():
    print(f"{n:5d}  {label}")

unmapped = [l for l, _ in keys.most_common() if "unmapped" in l]
if unmapped:
    print("\n== pressed but mapped to nothing ==")
    for label in unmapped:
        print(f"  {label}")
