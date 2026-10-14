"""Album art never blocks the deck loop, and a bad host can't fill the disk."""
import io
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from ragnaros import art
from ragnaros import daemon as ragnarosd


def png_bytes(color=(200, 30, 30), size=(64, 64)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


COVER = png_bytes()


@pytest.fixture(autouse=True)
def direct_loopback(monkeypatch):
    """The test server is on 127.0.0.1: reach it directly even where the
    environment sets a proxy (Debian's pybuild points http_proxy at a dead
    port so builds can't touch the network)."""
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")


@pytest.fixture
def server():
    release = threading.Event()
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            hits.append(self.path)
            if self.path == "/cover.png":
                self.send_response(200)
                self.send_header("Content-Length", str(len(COVER)))
                self.end_headers()
                self.wfile.write(COVER)
            elif self.path == "/stall":
                release.wait(10)  # accepts, then says nothing
            elif self.path == "/drip":
                self.send_response(200)
                self.end_headers()
                for _ in range(100):  # each read is quick, the whole is not
                    if release.wait(0.05):
                        return
                    self.wfile.write(b"x")
                    self.wfile.flush()
            elif self.path == "/declared-huge":
                self.send_response(200)
                self.send_header("Content-Length", str(50 * 1024 * 1024))
                self.end_headers()
            elif self.path == "/undeclared-huge":
                self.send_response(200)
                self.end_headers()
                try:
                    for _ in range(64):
                        self.wfile.write(b"\0" * 16384)
                except OSError:
                    pass
            else:
                self.send_error(404)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base, hits
    release.set()
    httpd.shutdown()
    httpd.server_close()


def loader(tmp_path, **kw):
    kw.setdefault("timeout", 0.3)
    kw.setdefault("deadline", 0.5)
    kw.setdefault("max_bytes", 200 * 1024)
    return art.ArtLoader(str(tmp_path / "art"), **kw)


def timed_get(arts, url):
    start = time.monotonic()
    img = arts.get(url)
    return img, time.monotonic() - start


def settle(arts, url, seconds=5.0):
    """Ask again until the worker for url is done, like the 1s strip tick does."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        img = arts.get(url)
        with arts._lock:
            busy = url in arts._pending or url in arts._ready
        if img is not None or not busy:
            return img
        time.sleep(0.02)
    raise AssertionError(f"art worker for {url} never finished")


def test_http_art_arrives_without_blocking_and_is_cached(tmp_path, server):
    base, hits = server
    arts = loader(tmp_path)
    url = f"{base}/cover.png"
    img, took = timed_get(arts, url)
    assert img is None and took < 0.1
    img = settle(arts, url)
    assert img.size == (64, 64)
    assert os.path.exists(arts.cache_path(url))
    assert arts.get(url) is img  # the same object while the track lasts

    # a restarted daemon loads it from the cache, not the network
    again = loader(tmp_path)
    assert settle(again, url).size == (64, 64)
    assert hits.count("/cover.png") == 1


def test_a_stalled_host_never_blocks_get(tmp_path, server):
    base, hits = server
    arts = loader(tmp_path)
    url = f"{base}/stall"
    for _ in range(5):
        img, took = timed_get(arts, url)
        assert img is None and took < 0.1
    assert settle(arts, url) is None  # gave up after the timeout
    assert not os.path.exists(arts.cache_path(url))
    assert hits.count("/stall") == 1  # five asks, one request


def test_a_dripping_host_is_cut_at_the_deadline(tmp_path, server):
    base, _ = server
    arts = loader(tmp_path, timeout=1.0, deadline=0.3)
    url = f"{base}/drip"
    start = time.monotonic()
    assert settle(arts, url) is None
    assert time.monotonic() - start < 2.0
    assert not os.path.exists(arts.cache_path(url))


@pytest.mark.parametrize("path", ["/declared-huge", "/undeclared-huge"])
def test_oversized_art_is_refused_and_leaves_no_file(tmp_path, server, path):
    base, _ = server
    arts = loader(tmp_path, max_bytes=100 * 1024)
    url = base + path
    arts.get(url)
    assert settle(arts, url) is None
    assert os.listdir(arts.cache_dir) == []  # no cached file, no .part left


def test_a_failed_url_waits_before_the_next_try(tmp_path, server):
    base, hits = server
    arts = loader(tmp_path, retry_seconds=0.3)
    url = f"{base}/missing.png"
    assert settle(arts, url) is None
    for _ in range(3):
        arts.get(url)
    assert hits.count("/missing.png") == 1
    time.sleep(0.35)
    arts.get(url)
    assert settle(arts, url) is None
    assert hits.count("/missing.png") == 2


def test_file_art_and_unknown_schemes(tmp_path):
    cover = tmp_path / "cover art.png"
    cover.write_bytes(COVER)
    arts = loader(tmp_path)
    url = "file://" + str(cover).replace(" ", "%20")
    assert settle(arts, url).size == (64, 64)
    for url in ("", None, "data:image/png;base64,AAAA", "ftp://example.com/a.png"):
        assert arts.get(url) is None


def test_now_playing_paints_at_once_while_the_cover_host_stalls(tmp_path, server):
    base, _ = server
    sent = []

    class Dev:
        def send_image(self, slot, data, strip=False):
            sent.append(slot)

        def flush(self):
            pass

    deck = ragnarosd.Deck.__new__(ragnarosd.Deck)
    deck.dev = Dev()
    deck.art = loader(tmp_path)
    deck.player = {"title": "Song", "artist": "Artist", "position": 1.0,
                   "length": 200.0, "art": f"{base}/stall", "ts": time.monotonic()}
    start = time.monotonic()
    deck.push_now_playing(time.monotonic())
    assert time.monotonic() - start < 1.0
    assert sent == [0, 1, 2, 3]
