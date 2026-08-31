#!/usr/bin/env python3
"""Fetch fresh JJK GIFs from Tenor into the strip rotation and update profiles.

Run manually or weekly via the ragnaros-gif-refresh systemd timer.
Usage: python3 tools/fetch_gifs.py [count]
"""
import os
import random
import re
import subprocess
import sys
import urllib.request

from PIL import Image, ImageSequence

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
SEG_DIR = os.path.join(ROOT, "assets", "gifs", "segments")
PROFILES = [os.path.join(ROOT, "profiles", n) for n in
            ("streaming.yaml", "ai-tools.yaml", "work.yaml", "stream.yaml")]
QUERIES = ["gojo-satoru", "sukuna", "nanami-jjk", "yuji-itadori", "megumi-fushiguro",
           "toji-jjk", "yuta-okkotsu", "nobara", "maki-zenin", "jujutsu-kaisen"]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
W, H = 176, 124
# user hand-picked anchors, always kept at the ends of the strip
ANCHOR_FIRST, ANCHOR_LAST = "gojo.gif", "nanami.gif"


def tenor_candidates(query):
    url = f"https://tenor.com/search/{query}-gifs"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
    except OSError:
        return []
    return sorted(set(re.findall(r'https://media\.tenor\.com/(\w+?)AAAAM/([\w%.-]+?)\.gif', html)))


def fetch(url_id, name):
    url = f"https://media1.tenor.com/m/{url_id}AAAAC/{name}.gif"
    path = f"/tmp/opencode/fetch_{url_id}.gif"
    r = subprocess.run(["curl", "-sL", "--max-time", "30", "-A", UA, "-o", path, url],
                       timeout=45)
    if r.returncode != 0 or not os.path.exists(path) or os.path.getsize(path) > 8_000_000:
        raise ValueError("download failed or too large")
    return path


def to_segment(src_path, dst_path, max_frames=40):
    img = Image.open(src_path)
    n = getattr(img, "n_frames", 1)
    if n < 8:
        raise ValueError("too few frames")
    step = max(1, n // max_frames)
    frames = []
    for i in range(0, n, step):
        img.seek(i)
        f = img.convert("RGB")
        scale = max(W / f.width, H / f.height)
        f = f.resize((int(f.width * scale) + 1, int(f.height * scale) + 1), Image.LANCZOS)
        x, y = (f.width - W) // 2, (f.height - H) // 2
        frames.append(f.crop((x, y, x + W, y + H)))
    frames[0].save(dst_path, save_all=True, append_images=frames[1:],
                   duration=90, loop=0, optimize=True)
    return len(frames)


def update_profiles(fresh):
    pool = sorted(b for b in os.listdir(SEG_DIR)
                  if b.endswith(".gif") and b not in (ANCHOR_FIRST, ANCHOR_LAST))
    picks = random.sample(pool, min(2, len(pool)))
    segments = [f"gifs/segments/{ANCHOR_FIRST}"] + [f"gifs/segments/{p}" for p in picks] + \
               [f"gifs/segments/{ANCHOR_LAST}"]
    block = "  segments:\n" + "".join(f"    - {s}\n" for s in segments)
    for path in PROFILES:
        if not os.path.exists(path):
            continue
        s = open(path).read()
        new = re.sub(r"  segments:\n(?:    - .*\n)+", block, s)
        if new != s:
            open(path, "w").write(new)
    return segments


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    os.makedirs(SEG_DIR, exist_ok=True)
    os.makedirs("/tmp/opencode", exist_ok=True)
    got = 0
    queries = random.sample(QUERIES, len(QUERIES))
    for query in queries:
        if got >= count:
            break
        candidates = random.sample(tenor_candidates(query),
                                   min(4, len(tenor_candidates(query) or [])))
        for url_id, name in candidates:
            try:
                src = fetch(url_id, name)
                dst = os.path.join(SEG_DIR, f"auto_{url_id[:8]}.gif")
                n = to_segment(src, dst)
                print(f"fetched {query}: {name} ({n} frames)")
                got += 1
                break
            except Exception as e:
                print(f"  skip {name}: {e}")
    segments = update_profiles(got)
    print("strip rotation:", segments)
    subprocess.run(["systemctl", "--user", "try-restart", "ragnarosd.service"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
