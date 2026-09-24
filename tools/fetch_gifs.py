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
THEMES = {
    "evangelion": {
        "queries": ["evangelion-unit-01", "asuka-evangelion", "rei-ayanami", "shinji-ikari", "evangelion-berserk"],
        "anchors": ("eva01.gif", "shinji.gif"),
    },
    "jjk": {
        "queries": ["gojo-satoru", "sukuna", "nanami-jjk", "yuji-itadori", "megumi-fushiguro",
                    "toji-jjk", "yuta-okkotsu", "nobara", "maki-zenin", "jujutsu-kaisen"],
        "anchors": ("auto_5LhLOxI5.gif", "auto_LmA9KL1I.gif"),
    },
}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
W, H = 176, 124
ANCHOR_FIRST, ANCHOR_LAST = "eva01.gif", "shinji.gif"


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
    from PIL import ImageChops, ImageStat
    img = Image.open(src_path)
    n = getattr(img, "n_frames", 1)
    if n < 8:
        raise ValueError("too few frames")
    step = max(1, (n + max_frames - 1) // max_frames)
    frames = []
    for i in range(0, n, step):
        img.seek(i)
        f = img.convert("RGB")
        # trim black letterboxing bars
        bg = Image.new(f.mode, f.size, (0, 0, 0))
        diff = ImageChops.difference(f, bg)
        bbox = diff.convert("L").point(lambda x: 255 if x > 15 else 0).getbbox()
        if bbox:
            f = f.crop(bbox)
        # drop dark flat frames (gaps/black tails that read as LCD flashes)
        st = ImageStat.Stat(f.convert("L").resize((64, 45)))
        if st.stddev[0] < 18 and st.mean[0] < 30:
            continue
        scale = max(W / f.width, H / f.height)
        f = f.resize((int(f.width * scale) + 1, int(f.height * scale) + 1), Image.LANCZOS)
        x, y = (f.width - W) // 2, max(0, int((f.height - H) * 0.3))
        frames.append(f.crop((x, y, x + W, y + H)))
    if len(frames) < 8:
        raise ValueError("too few frames after black-frame filter")
    frames[0].save(dst_path, save_all=True, append_images=frames[1:],
                   duration=40, loop=0, optimize=True)
    return len(frames)


def detect_theme():
    cfg = os.path.join(ROOT, "profiles", "streaming.yaml")
    if os.path.exists(cfg):
        content = open(cfg).read()
        if "eva" in content or "asuka" in content:
            return "evangelion"
    return "jjk"


def update_profiles(fresh, theme="evangelion"):
    cfg = THEMES.get(theme, THEMES["evangelion"])
    anchor_first, anchor_last = cfg["anchors"]
    pool = sorted(b for b in os.listdir(SEG_DIR)
                  if b.endswith(".gif") and b not in (anchor_first, anchor_last))
    # show freshly fetched GIFs first; at most 2 middles (2 slots stay for anchors)
    middle = random.sample(fresh, min(2, len(fresh)))
    if len(middle) < 2:
        middle += [b for b in random.sample(pool, min(2 - len(middle), len(pool)))
                   if b not in middle]
    segments = [f"gifs/segments/{anchor_first}"] + [f"gifs/segments/{p}" for p in middle] + \
               [f"gifs/segments/{anchor_last}"]
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
    theme = "evangelion" if "--evangelion" in sys.argv else ("jjk" if "--jjk" in sys.argv else detect_theme())
    count = 3
    for arg in sys.argv[1:]:
        if arg.isdigit():
            count = int(arg)
    os.makedirs(SEG_DIR, exist_ok=True)
    os.makedirs("/tmp/opencode", exist_ok=True)
    got = 0
    fresh = []
    queries = random.sample(THEMES[theme]["queries"], len(THEMES[theme]["queries"]))
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
                fresh.append(os.path.basename(dst))
                got += 1
                break
            except Exception as e:
                print(f"  skip {name}: {e}")
    if fresh:
        segments = update_profiles(fresh, theme=theme)
        print("strip rotation:", segments)
    subprocess.run(["systemctl", "--user", "try-restart", "ragnarosd.service"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
