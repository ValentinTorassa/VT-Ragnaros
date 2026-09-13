import io

import pytest
from PIL import Image

import renderer

STRIP_FULL = (704, 124)


def test_to_jpeg_returns_jpeg_bytes():
    img = Image.new("RGB", (176, 124), (10, 20, 30))
    data = renderer.to_jpeg(img)
    assert data[:2] == b"\xff\xd8"
    reopened = Image.open(io.BytesIO(data))
    assert reopened.size == (176, 124)


def test_now_playing_strip_layout():
    img = renderer.now_playing_strip("Title", "Artist", 30, 120, STRIP_FULL)
    assert img.size == STRIP_FULL
    assert img.mode == "RGB"


def test_now_playing_art_fills_the_first_card():
    """Art covers its 176x124 panel edge to edge - no bands, no squash."""
    art = Image.new("RGB", (300, 200), (200, 10, 10))
    img = renderer.now_playing_strip("Title", "Artist", 30, 120, STRIP_FULL, art=art)
    for corner in ((0, 0), (175, 0), (0, 123), (175, 123), (88, 62)):
        assert img.getpixel(corner) == (200, 10, 10)


def test_now_playing_keeps_the_panel_seams_clear():
    """Nothing may be painted across a bezel between two panels."""
    img = renderer.now_playing_strip(
        "Everything In Its Right Place", "Thom Yorke And The Whole Band",
        90, 251, STRIP_FULL, art=Image.new("RGB", (300, 300), (200, 10, 10)))
    # card 0 is the cover art and owns its panel up to x=175
    for x in list(range(176, 180)) + [x for s in (352, 528) for x in range(s - 4, s + 4)]:
        column = [img.getpixel((x, y)) for y in range(124)]
        assert set(column) == {(0, 0, 0)}, f"ink on the seam at x={x}"


def test_overlay_strip_keeps_the_panel_seams_clear():
    img = renderer.overlay_strip("BRIGHTNESS", 0.62, STRIP_FULL)
    for seam in (176, 352, 528):
        for x in range(seam - 4, seam + 4):
            column = [img.getpixel((x, y)) for y in range(124)]
            assert set(column) == {(0, 0, 0)}, f"ink on the seam at x={x}"


def test_now_playing_zero_length_does_not_divide_by_zero():
    renderer.now_playing_strip("Title", "Artist", 5, 0, STRIP_FULL)


def test_overlay_strip_clamps_fraction():
    for frac in (-2.0, 0.0, 0.5, 1.0, 7.5):
        img = renderer.overlay_strip("VOLUME", frac, STRIP_FULL)
        assert img.size == STRIP_FULL


@pytest.mark.parametrize("path", [renderer.FONT, renderer.FONT_BOLD])
def test_load_font_falls_back(path, monkeypatch):
    monkeypatch.setattr(renderer, "FONT", "/nonexistent/font.ttf")
    monkeypatch.setattr(renderer, "FONT_BOLD", "/nonexistent/font.ttf")
    font = renderer.load_font(path, 20)
    assert font is not None
