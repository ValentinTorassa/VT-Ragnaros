#!/usr/bin/env python3
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))

from PIL import Image, ImageDraw
from protocol import KEY_COUNT, KEY_LCD, Ragnaros

SIZE = tuple(int(a) for a in (sys.argv[1].split("x") if len(sys.argv) > 1 else KEY_LCD))

COLORS = [
    (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255),
    (0, 255, 255), (255, 128, 0), (128, 0, 255), (0, 128, 255), (255, 255, 255),
]


def make_jpeg(color, label):
    img = Image.new("RGB", SIZE, color)
    d = ImageDraw.Draw(img)
    d.text((5, 5), label, fill=(0, 0, 0) if sum(color) > 380 else (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


deck = Ragnaros()
deck.initialize()
deck.clear_all()
for key in range(KEY_COUNT):
    deck.send_image(key, make_jpeg(COLORS[key], str(key)))
deck.flush()
print(f"sent {KEY_COUNT} {SIZE[0]}x{SIZE[1]} JPEGs - check the deck")
time.sleep(5)
