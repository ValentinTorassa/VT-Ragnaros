#!/usr/bin/env python3
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))

from PIL import Image, ImageDraw
from protocol import Ragnaros

SLOTS = 14
SIZE = (60, 60)

PALETTE = [
    (230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48),
    (145, 30, 180), (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212),
    (0, 128, 128), (220, 190, 255), (170, 110, 40), (128, 128, 0),
]


def make_jpeg(color, label):
    img = Image.new("RGB", SIZE, color)
    d = ImageDraw.Draw(img)
    d.rectangle((12, 12, 48, 48), fill=(0, 0, 0))
    d.text((24, 22), label, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


deck = Ragnaros()
deck.initialize()
deck.clear_all()
for slot in range(SLOTS):
    deck.send_image(slot, make_jpeg(PALETTE[slot], str(slot)))
deck.flush()
print(f"painted slots 0-{SLOTS-1} with big numbers")
print("report: top row (5), bottom row (5), strip (4): which number where?")
time.sleep(120)
