#!/usr/bin/env python3
import os
import selectors
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))

from protocol import Ragnaros

deck = Ragnaros()
deck.initialize()
deck.set_brightness(100)
time.sleep(0.3)
deck.set_brightness(30)
time.sleep(0.3)
deck.set_brightness(80)
print("brightness pulsed - did the screen react?")

sel = selectors.DefaultSelector()
sel.register(deck.fd, selectors.EVENT_READ, "vendor")
try:
    kbd = os.open("/dev/hidraw8", os.O_RDONLY | os.O_NONBLOCK)
    sel.register(kbd, selectors.EVENT_READ, "kbd")
except OSError as e:
    print(f"no kbd node: {e}")

print("listening 30s on both interfaces - press keys, turn knobs")
t0 = time.monotonic()
while time.monotonic() - t0 < 30:
    for key, _ in sel.select(timeout=0.05):
        try:
            data = os.read(key.fd, 512)
        except BlockingIOError:
            continue
        if data:
            print(f"{time.monotonic()-t0:7.3f} {key.data:6s} {len(data):3d}B {data[:24].hex(' ')}")
