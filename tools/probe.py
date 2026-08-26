#!/usr/bin/env python3
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))

from protocol import Ragnaros

deck = Ragnaros()
print("== feature report probes ==")
for rid in range(0, 4):
    try:
        data = deck.get_feature_report(rid, 32)
        print(f"feature {rid}: {data.hex(' ')}")
    except RuntimeError as e:
        print(f"feature {rid}: {e}")

print("== magic command probes (keep pressing keys!) ==")
CANDIDATES = [
    b"SWE", b"DAT", b"OK", b"ROTI", b"ACK", b"GET", b"KEY", b"RPT",
    b"START", b"EN", b"ON", b"READ", b"POLL", b"INIT", b"VER", b"FW",
    b"SN", b"INFO", b"STATE", b"BTN", b"ENC", b"KNOB", b"EVT", b"EVENT",
    b"IN", b"INPUT", b"RUN", b"GO", b"ACT", b"OPEN", b"HOST", b"PC",
]

deck.initialize()


def drain(window=0.35):
    end = time.monotonic() + window
    while time.monotonic() < end:
        data = deck.transfer(0x82, bytes(512), 50)
        if data:
            print(f"  INPUT! {len(data)}B {data[:32].hex(' ')}")
            return True
    return False


for magic in CANDIDATES:
    tail = list(magic)
    deck.command(*tail)
    if drain():
        print(f"^^ triggered by CRT+{magic!r}")
        break
else:
    print("no CRT-prefixed magic worked, trying raw prefixes")
    RAW = [
        bytes([0x00, 0x55, 0xAA, 0x55, 0xAA]),
        bytes([0x00, 0xA5, 0xA5, 0xA5, 0xA5]),
        bytes([0x00, 0x53, 0x57, 0x45, 0x00, 0x00, 0x01]),
        bytes([0x00, 0x01]),
        bytes([0x00, 0x02]),
        bytes([0x00, 0x03]),
    ]
    for payload in RAW:
        deck.write(payload)
        if drain():
            print(f"^^ triggered by {payload.hex(' ')}")
            break
    else:
        print("all probes exhausted - final 15s open listen, PRESS EVERYTHING")
        drain(15)
print("done")
