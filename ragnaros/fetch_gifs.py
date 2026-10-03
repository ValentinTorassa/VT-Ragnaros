"""Opt-in: download an anime GIF theme for the strip idle face.

The GIFs come from Tenor search results and belong to their owners, so
they are never bundled: they land in your data directory
(~/.local/share/ragnaros/gifs), and the rotation is written to
gifs/theme.yaml there. Profiles without their own strip.segments pick it up
within a couple of seconds; nothing in the repository or the package changes.

  ragnaros-fetch-gifs                    fetch 3 new GIFs for the current theme
  ragnaros-fetch-gifs --theme jjk 4      pick a theme (jjk, evangelion) and count
  ragnaros-fetch-gifs --off              drop the theme: back to the bundled idle art
                                         (the downloaded GIFs stay until you delete them)

Run it by hand, or weekly with the ragnaros-gif-refresh.timer user unit.
"""
import argparse
import os
import random
import re
import sys
import tempfile
import urllib.request

from PIL import Image, ImageChops, ImageStat

from . import paths, theme

THEMES = {
    "evangelion": ["evangelion-unit-01", "asuka-evangelion", "rei-ayanami", "shinji-ikari",
                   "evangelion-berserk"],
    "jjk": ["gojo-satoru", "sukuna", "nanami-jjk", "yuji-itadori", "megumi-fushiguro",
            "toji-jjk", "yuta-okkotsu", "nobara", "maki-zenin", "jujutsu-kaisen"],
}
DEFAULT_THEME = "jjk"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
W, H = 176, 124  # one strip panel
PANELS = 4
MAX_DOWNLOAD = 8_000_000


def seg_dir():
    return os.path.join(paths.gif_dir(), "segments")


def tenor_candidates(query):
    url = f"https://tenor.com/search/{query}-gifs"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", "replace")
    except OSError:
        return []
    return sorted(set(re.findall(r'https://media\.tenor\.com/(\w+?)AAAAM/([\w%.-]+?)\.gif', html)))


def fetch(url_id, name, workdir):
    url = f"https://media1.tenor.com/m/{url_id}AAAAC/{name}.gif"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    path = os.path.join(workdir, f"fetch_{url_id}.gif")
    with urllib.request.urlopen(req, timeout=30) as resp, open(path, "wb") as out:
        data = resp.read(MAX_DOWNLOAD + 1)
        if len(data) > MAX_DOWNLOAD:
            raise ValueError("too large")
        out.write(data)
    return path


def to_segment(src_path, dst_path, max_frames=40):
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


def pick_rotation(fresh, available, anchors=()):
    """Four panel GIFs (file names): the anchors keep the end panels, the
    freshly fetched ones go in between, older downloads fill any gap."""
    anchors = [a for a in anchors if a in available][:2]
    slots = PANELS - len(anchors)
    middle = random.sample(fresh, min(slots, len(fresh)))
    pool = [b for b in available if b not in anchors and b not in middle]
    middle += random.sample(pool, min(slots - len(middle), len(pool)))
    return anchors[:1] + middle + anchors[1:]


def download(theme_name, count, workdir, log=print):
    fresh = []
    queries = random.sample(THEMES[theme_name], len(THEMES[theme_name]))
    for query in queries:
        if len(fresh) >= count:
            break
        candidates = tenor_candidates(query)
        for url_id, name in random.sample(candidates, min(4, len(candidates))):
            try:
                src = fetch(url_id, name, workdir)
                dst = os.path.join(seg_dir(), f"auto_{url_id[:8]}.gif")
                n = to_segment(src, dst)
                log(f"fetched {query}: {name} ({n} frames)")
                fresh.append(os.path.basename(dst))
                break
            except Exception as error:
                log(f"  skip {name}: {error}")
    return fresh


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ragnaros-fetch-gifs",
        description="Opt-in: download an anime GIF theme from Tenor into "
                    f"{paths.gif_dir()} and make it the strip's idle rotation.")
    parser.add_argument("count", nargs="?", type=int, default=3,
                        help="how many new GIFs to fetch (default 3)")
    parser.add_argument("--theme", choices=sorted(THEMES),
                        help="theme to fetch (default: the current one, else jjk)")
    parser.add_argument("--jjk", dest="theme", action="store_const", const="jjk",
                        help=argparse.SUPPRESS)
    parser.add_argument("--evangelion", dest="theme", action="store_const", const="evangelion",
                        help=argparse.SUPPRESS)
    parser.add_argument("--off", action="store_true",
                        help="remove theme.yaml so the strip goes back to the bundled art")
    args = parser.parse_args(argv)

    data = theme.load()
    if args.off:
        try:
            os.remove(theme.path())
            print(f"removed {theme.path()}; the GIFs stay in {seg_dir()}")
        except FileNotFoundError:
            print("no GIF theme set")
        return 0

    name = args.theme or data.get("theme")
    if name not in THEMES:
        name = DEFAULT_THEME
    os.makedirs(seg_dir(), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ragnaros-gifs-") as workdir:
        fresh = download(name, args.count, workdir)
    if not fresh and theme.segments_for(data):
        print("nothing new fetched; keeping the current rotation")
        return 0
    available = sorted(b for b in os.listdir(seg_dir()) if b.endswith(".gif"))
    if not available:
        print("nothing downloaded and no earlier GIFs to use", file=sys.stderr)
        return 1
    anchors = ((data.get("anchors") or {}).get(name) or []) if isinstance(
        data.get("anchors"), dict) else []
    rotation = [f"gifs/segments/{b}" for b in pick_rotation(fresh, available, anchors)]
    data.update(theme=name, segments=rotation)
    theme.save(data)
    print("strip rotation:", rotation)
    return 0


if __name__ == "__main__":
    sys.exit(main())
