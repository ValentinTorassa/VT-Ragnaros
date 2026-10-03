"""Where profiles, assets and the opt-in GIF theme come from."""
import os

import pytest
from PIL import Image

from ragnaros import daemon as ragnarosd
from ragnaros import fetch_gifs, paths, theme


@pytest.fixture
def roots(tmp_path, monkeypatch):
    config, data = tmp_path / "config", tmp_path / "data"
    monkeypatch.setenv("RAGNAROS_CONFIG", str(config))
    monkeypatch.setenv("RAGNAROS_DATA", str(data))
    return config, data


def gif(path, color=(200, 40, 40), frames=8):
    path.parent.mkdir(parents=True, exist_ok=True)
    images = [Image.new("RGB", (176, 124), color) for _ in range(frames)]
    images[0].save(path, save_all=True, append_images=images[1:], duration=40)
    return path


def deck_with(profile):
    deck = ragnarosd.Deck.__new__(ragnarosd.Deck)
    deck.profile = profile
    deck.theme = theme.load()
    return deck


# -- paths ----------------------------------------------------------------------
def test_bundled_trees_resolve_in_a_checkout():
    for name in ("profiles", "assets", "udev", os.path.join("packaging", "systemd")):
        assert os.path.isdir(paths.bundled(name)), name


def test_assets_search_config_then_data_then_bundled(roots):
    config, data = roots
    assert paths.find_asset("icons/lock.png").startswith(paths.bundled("assets"))
    gif(data / "icons" / "lock.png")
    assert paths.find_asset("icons/lock.png") == str(data / "icons" / "lock.png")
    gif(config / "assets" / "icons" / "lock.png")
    assert paths.find_asset("icons/lock.png") == str(config / "assets" / "icons" / "lock.png")
    assert paths.find_asset("icons/nope.png") is None
    assert paths.find_asset(None) is None


def test_a_config_profile_overrides_the_bundled_one(roots):
    config, _ = roots
    bundled = paths.profile_path("streaming")
    assert bundled.startswith(paths.bundled("profiles"))
    (config / "profiles").mkdir(parents=True)
    (config / "profiles" / "streaming.yaml").write_text("name: streaming\n")
    (config / "profiles" / "mine.yaml").write_text("name: mine\n")
    assert paths.profile_path("streaming") == str(config / "profiles" / "streaming.yaml")
    assert {"mine", "streaming", "work"} <= set(paths.available_profiles())


# -- the idle strip: profile, then theme, then bundled art -------------------------
def test_without_a_theme_the_strip_idles_on_bundled_art(roots):
    deck = deck_with({"_name": "streaming", "strip": {}})
    assert deck.idle_segments() == list(ragnarosd.DEFAULT_SEGMENTS)


def test_a_downloaded_theme_feeds_profiles_without_segments(roots):
    _, data = roots
    for name in ("a", "b", "c", "d"):
        gif(data / "gifs" / "segments" / f"{name}.gif")
    theme.save({"theme": "jjk",
                "segments": [f"gifs/segments/{n}.gif" for n in "abcd"],
                "profiles": {"system": ["gifs/segments/d.gif"]}})
    assert deck_with({"_name": "work"}).idle_segments() == \
        [f"gifs/segments/{n}.gif" for n in "abcd"]
    assert deck_with({"_name": "system"}).idle_segments() == ["gifs/segments/d.gif"]
    # the profile's own list and a full-strip GIF both win over the theme
    own = {"_name": "work", "strip": {"segments": ["strip/default_1.gif"]}}
    assert deck_with(own).idle_segments() == ["strip/default_1.gif"]
    assert deck_with({"_name": "work", "strip": {"gif": "x.gif"}}).idle_segments() is None


def test_theme_gifs_missing_on_disk_fall_back_to_bundled_art(roots):
    theme.save({"segments": ["gifs/segments/deleted.gif"]})
    assert deck_with({"_name": "work"}).idle_segments() == list(ragnarosd.DEFAULT_SEGMENTS)


def test_the_daemon_notices_a_new_theme(roots):
    deck = deck_with({"_name": "work"})
    deck._theme_mtime = theme.mtime()
    deck.idle_face, deck.idle_playing = "gifs", True
    theme.save({"segments": ["strip/default_2.gif"]})
    deck.maybe_reload_theme()
    assert deck.theme["segments"] == ["strip/default_2.gif"]
    assert deck.idle_playing is False


def test_a_broken_theme_file_is_ignored(roots):
    _, data = roots
    (data / "gifs").mkdir(parents=True)
    (data / "gifs" / "theme.yaml").write_text("segments: [unclosed\n")
    assert theme.load() == {}
    assert theme.segments_for({"segments": "not-a-list"}) == []


# -- ragnaros-fetch-gifs ------------------------------------------------------------
def test_rotation_keeps_anchors_on_the_end_panels():
    rotation = fetch_gifs.pick_rotation(["new1.gif", "new2.gif"],
                                        ["eva01.gif", "new1.gif", "new2.gif", "old.gif",
                                         "shinji.gif"],
                                        anchors=["eva01.gif", "shinji.gif"])
    assert rotation[0] == "eva01.gif" and rotation[-1] == "shinji.gif"
    assert sorted(rotation[1:3]) == ["new1.gif", "new2.gif"]


def test_rotation_without_anchors_fills_four_panels():
    rotation = fetch_gifs.pick_rotation(["n.gif"], ["n.gif", "o1.gif", "o2.gif", "o3.gif"],
                                        anchors=["gone.gif"])
    assert len(rotation) == 4 and "n.gif" in rotation and len(set(rotation)) == 4


def test_fetch_writes_only_the_data_dir(roots, monkeypatch):
    _, data = roots
    profiles_before = {p: open(os.path.join(paths.bundled("profiles"), p)).read()
                       for p in os.listdir(paths.bundled("profiles"))}

    def fake_download(name, count, workdir, log=print):
        assert name == "evangelion"
        return [gif(data / "gifs" / "segments" / f"auto_{i}.gif").name for i in range(count)]

    monkeypatch.setattr(fetch_gifs, "download", fake_download)
    assert fetch_gifs.main(["--theme", "evangelion", "2"]) == 0
    saved = theme.load()
    assert saved["theme"] == "evangelion"
    assert sorted(saved["segments"]) == ["gifs/segments/auto_0.gif", "gifs/segments/auto_1.gif"]
    assert all(paths.find_asset(s).startswith(str(data)) for s in saved["segments"])
    for name, text in profiles_before.items():
        assert open(os.path.join(paths.bundled("profiles"), name)).read() == text

    # offline: nothing new, the rotation stays as it was
    monkeypatch.setattr(fetch_gifs, "download", lambda *a, **k: [])
    assert fetch_gifs.main([]) == 0
    assert theme.load()["segments"] == saved["segments"]

    assert fetch_gifs.main(["--off"]) == 0
    assert not os.path.exists(theme.path())
    assert deck_with({"_name": "work"}).idle_segments() == list(ragnarosd.DEFAULT_SEGMENTS)
