#!/usr/bin/env python3
"""Test the official HANDLER -> HAN handshake against the deck.

Verified from SDLibrary1.dll:
  - The device sends an input packet beginning with "HANDLER".
  - The app replies with hid_write of [0x00,'H','A','N', zeros...]
    (sendHandshakePack @ RVA 0x1eb00, wire bytes: 48 41 4E + zeros on EP 0x03).
  - The app never sends the handshake unsolicited; it only replies.

This tool:
  1. waits for the deck (replug while waiting to catch a boot-time HANDLER),
  2. listens briefly for any spontaneous input,
  3. sends the raw HAN reply,
  4. dumps every input packet (raw hex + parsed) for LISTEN_SECONDS.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))

from inputmap import parse_input
from protocol import Ragnaros

WAIT_SECONDS = float(os.environ.get("WAIT_SECONDS", "20"))
LISTEN_SECONDS = float(os.environ.get("LISTEN_SECONDS", "45"))

deck = None
t_wait = time.monotonic()
while time.monotonic() - t_wait < WAIT_SECONDS:
    try:
        deck = Ragnaros()
        break
    except Exception as e:
        print(f"waiting for deck... ({e})", flush=True)
        time.sleep(1)
if deck is None:
    sys.exit("deck not found")

print(f"opened {deck.path}", flush=True)


def pump(window, label):
    end = time.monotonic() + window
    got = False
    while time.monotonic() < end:
        data = deck.transfer(0x82, bytes(512), 100)
        if data:
            got = True
            event = parse_input(data)
            print(f"[{label}] IN {len(data)}B {data[:32].hex(' ')} parsed={event}", flush=True)
    return got


print("phase 1: passive listen 5s (press nothing yet)", flush=True)
pump(5, "pre-HAN")

print("phase 2: sending raw HAN handshake reply", flush=True)
deck.write([0x00, 0x48, 0x41, 0x4E])

print(f"phase 3: listen {LISTEN_SECONDS:.0f}s - PRESS KEYS, TURN/PRESS KNOBS, TOUCH STRIP", flush=True)
pump(LISTEN_SECONDS, "post-HAN")

print("phase 4: no luck? trying CRT-prefixed HAN + DIS/LIG then 15s more", flush=True)
deck.initialize()
deck.sleep()  # CRT-prefixed HAN (previously known 'sleep' command)
pump(15, "post-CRT")

deck.close()
print("done", flush=True)
