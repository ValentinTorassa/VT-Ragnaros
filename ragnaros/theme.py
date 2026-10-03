"""The optional strip GIF theme: <data dir>/gifs/theme.yaml.

ragnaros-fetch-gifs writes it; the daemon reads it for every profile that
does not name its own strip.segments. Without the file the strip idles on
the bundled generated art.

    theme: jjk                       # last theme fetched
    anchors:                         # per theme: GIFs that keep the end panels
      jjk: [gojo.gif, yuta.gif]
    segments:                        # the rotation, asset-relative paths
      - gifs/segments/auto_xxxxxxxx.gif
    profiles:                        # optional per-profile rotations
      system: [gifs/segments/a.gif, gifs/segments/b.gif]
"""
import os

import yaml

from . import paths

HEADER = ("# Strip GIF theme, written by ragnaros-fetch-gifs. Profiles without their\n"
          "# own strip.segments idle on these; delete this file to go back to the\n"
          "# bundled idle art.\n")


def path():
    return os.path.join(paths.gif_dir(), "theme.yaml")


def mtime():
    try:
        return os.path.getmtime(path())
    except OSError:
        return None


def load():
    try:
        with open(path()) as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data):
    os.makedirs(paths.gif_dir(), exist_ok=True)
    tmp = path() + ".tmp"
    with open(tmp, "w") as f:
        f.write(HEADER)
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=None)
    os.replace(tmp, path())  # the daemon polls this file: never show it half-written


def _gif_list(value):
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v]


def segments_for(data, profile_name=None):
    """The theme rotation for one profile: its own entry, else the default."""
    own = _gif_list((data.get("profiles") or {}).get(profile_name)) if profile_name else []
    return own or _gif_list(data.get("segments"))
