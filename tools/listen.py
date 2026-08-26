#!/usr/bin/env python3
import os
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
print("listening 30s - press keys, turn knobs")
t0 = time.monotonic()
try:
    while time.monotonic() - t0 < 30:
        event = deck.poll(50)
        if event:
            print(f"{time.monotonic()-t0:7.3f} {event}")
finally:
    deck.close()
