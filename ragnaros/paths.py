"""Where ragnaros finds profiles, images and downloaded GIF themes.

Assets named in a profile (icons/brave.png, gifs/segments/x.gif) are looked
up in three roots, first match wins:

  1. config   $RAGNAROS_CONFIG/assets  (default ~/.config/ragnaros/assets)
  2. data     $RAGNAROS_DATA           (default ~/.local/share/ragnaros),
              where ragnaros-fetch-gifs puts GIF themes under gifs/
  3. bundled  the assets shipped with the package, or assets/ in a checkout

Profiles come from $RAGNAROS_CONFIG/profiles first, then the bundled ones.
"""
import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
# a git checkout keeps profiles/, assets/, udev/ ... next to the package;
# a wheel carries the same trees inside it
CHECKOUT_DIR = os.path.dirname(PACKAGE_DIR)


def config_dir():
    return os.environ.get("RAGNAROS_CONFIG") or os.path.expanduser("~/.config/ragnaros")


def data_dir():
    if os.environ.get("RAGNAROS_DATA"):
        return os.environ["RAGNAROS_DATA"]
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "ragnaros")


def gif_dir():
    return os.path.join(data_dir(), "gifs")


def bundled(name):
    """A tree shipped with ragnaros: inside the installed package, or at the
    root of the git checkout the package was imported from."""
    for base in (PACKAGE_DIR, CHECKOUT_DIR):
        path = os.path.join(base, name)
        if os.path.isdir(path):
            return path
    return os.path.join(PACKAGE_DIR, name)


def asset_roots():
    return [os.path.join(config_dir(), "assets"), data_dir(), bundled("assets")]


def find_asset(rel):
    """Absolute path of an existing asset, or None."""
    if not isinstance(rel, str) or not rel:
        return None
    rel = os.path.expanduser(rel)
    if os.path.isabs(rel):
        return rel if os.path.exists(rel) else None
    for root in asset_roots():
        path = os.path.join(root, rel)
        if os.path.exists(path):
            return path
    return None


def profile_dirs():
    return [os.path.join(config_dir(), "profiles"), bundled("profiles")]


def profile_path(name):
    """The profile file that wins for this name (it may not exist)."""
    dirs = profile_dirs()
    for directory in dirs:
        path = os.path.join(directory, f"{name}.yaml")
        if os.path.exists(path):
            return path
    return os.path.join(dirs[-1], f"{name}.yaml")


def available_profiles():
    names = set()
    for directory in profile_dirs():
        try:
            names.update(f[:-5] for f in os.listdir(directory) if f.endswith(".yaml"))
        except OSError:
            pass
    return sorted(names)
