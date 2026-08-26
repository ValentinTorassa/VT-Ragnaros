#!/usr/bin/env python3
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))

from protocol import Ragnaros

deck = Ragnaros()
deck.initialize()

print("== control-channel input polling, 15s, PRESS KEYS ==")
t0 = time.monotonic()
last = None
while time.monotonic() - t0 < 15:
    try:
        b = deck.get_input_report(0, 512)
        if b != last and any(b):
            print(f"{time.monotonic()-t0:7.3f} {b[:32].hex(' ')}")
            last = b
    except RuntimeError as e:
        print(f"ginput: {e}")
        break
    time.sleep(0.05)

print("== SET feature enable candidates ==")
CANDIDATES = [
    bytes([0x01]), bytes([0x02]), bytes([0x03]), bytes([0x01, 0x01]),
    b"\x00CRT\x00\x00CONNECT", b"\x00CRT\x00\x00DIS", b"\x00CRT\x00\x00EN",
]
for payload in CANDIDATES:
    buf = payload + b"\x00" * (512 - len(payload))
    try:
        deck.send_feature_report(buf)
        print(f"sfeature {payload[:12].hex(' ')}: ok")
    except RuntimeError as e:
        print(f"sfeature {payload[:12].hex(' ')}: {e}")
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        data = deck.transfer(0x82, bytes(512), 50)
        if data:
            print(f"  INTERRUPT IN! {data[:32].hex(' ')}")

print("== final 10s: poll ginput + interrupt, PRESS EVERYTHING ==")
t0 = time.monotonic()
while time.monotonic() - t0 < 10:
    try:
        b = deck.get_input_report(0, 512)
        if any(b):
            print(f"{time.monotonic()-t0:7.3f} ginput {b[:32].hex(' ')}")
    except RuntimeError:
        pass
    data = deck.transfer(0x82, bytes(512), 50)
    if data:
        print(f"{time.monotonic()-t0:7.3f} int-in {data[:32].hex(' ')}")
print("done")
