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


def test_now_playing_strip_with_art_shifts_text():
    art = Image.new("RGB", (300, 300), (200, 10, 10))
    img = renderer.now_playing_strip("Title", "Artist", 30, 120, STRIP_FULL, art=art)
    assert img.size == STRIP_FULL
    # art thumbnail pasted near the left edge must be non-black now
    assert img.getpixel((60, 62)) != (0, 0, 0)


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
