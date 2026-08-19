#!/usr/bin/env python3
import fcntl
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))

from protocol import Ragnaros

IOCGINPUT = lambda n: (3 << 30) | (ord("H") << 8) | 0x0A | (n << 16)
IOCSFEATURE = lambda n: (3 << 30) | (ord("H") << 8) | 0x06 | (n << 16)

deck = Ragnaros()
deck.initialize()

print("== control-channel input polling, 15s, PRESS KEYS ==")
t0 = time.monotonic()
last = None
while time.monotonic() - t0 < 15:
    buf = bytearray(512)
    try:
        fcntl.ioctl(deck.fd, IOCGINPUT(512), buf, True)
        b = bytes(buf)
        if b != last and any(b):
            print(f"{time.monotonic()-t0:7.3f} {b[:32].hex(' ')}")
            last = b
    except OSError as e:
        print(f"ginput: {e}")
        break
    time.sleep(0.05)

print("== SET feature enable candidates ==")
CANDIDATES = [
    bytes([0x01]), bytes([0x02]), bytes([0x03]), bytes([0x01, 0x01]),
    b"\x00CRT\x00\x00CONNECT", b"\x00CRT\x00\x00DIS", b"\x00CRT\x00\x00EN",
]
for payload in CANDIDATES:
    buf = bytearray(512)
    buf[: len(payload)] = payload
    try:
        fcntl.ioctl(deck.fd, IOCSFEATURE(512), buf, True)
        print(f"sfeature {payload[:12].hex(' ')}: ok")
    except OSError as e:
        print(f"sfeature {payload[:12].hex(' ')}: {e}")
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        try:
            data = os.read(deck.fd, 512)
            if data:
                print(f"  INTERRUPT IN! {data[:32].hex(' ')}")
        except BlockingIOError:
            time.sleep(0.01)

print("== final 10s: poll ginput + interrupt, PRESS EVERYTHING ==")
t0 = time.monotonic()
while time.monotonic() - t0 < 10:
    buf = bytearray(512)
    try:
        fcntl.ioctl(deck.fd, IOCGINPUT(512), buf, True)
        if any(buf):
            print(f"{time.monotonic()-t0:7.3f} ginput {bytes(buf[:32]).hex(' ')}")
    except OSError:
        pass
    try:
        data = os.read(deck.fd, 512)
        if data:
            print(f"{time.monotonic()-t0:7.3f} int-in {data[:32].hex(' ')}")
    except BlockingIOError:
        pass
    time.sleep(0.05)
print("done")
