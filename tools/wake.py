#!/usr/bin/env python3
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))

from protocol import Ragnaros

deck = Ragnaros()
print(f"opened {deck.path}")
deck.initialize()
print("sent init (DIS + LIG)")
deck.set_brightness(80)
print("brightness 80")
deck.clear_all()
print("cleared all keys")
print("press keys / turn knobs / press knobs - printing raw codes for 30s")
t0 = time.monotonic()
while time.monotonic() - t0 < 30:
    event = deck.poll()
    if event:
        print(f"{time.monotonic()-t0:7.3f} code=0x{event[0]:02x} state={event[1]}")
    time.sleep(0.01)
deck.set_brightness(50)
