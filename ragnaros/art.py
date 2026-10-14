"""Album art for the now-playing strip, loaded without blocking the deck loop.

The daemon runs one loop for keys, knobs, the strip and the USB keepalive, so
nothing in it may wait on the network. ArtLoader.get() never does I/O: it
hands back the image once a worker thread has fetched and decoded it, and
None until then (the strip draws without a cover meanwhile).

http(s) art is downloaded with a per-read timeout, an overall deadline and a
size cap, into a cache keyed by the URL's hash, so a stalled or hostile host
costs one worker thread for a few seconds and nothing else.
"""
import hashlib
import os
import sys
import threading
import time
import urllib.parse
import urllib.request

from PIL import Image

TIMEOUT = 5.0  # seconds per connect/read
DEADLINE = 15.0  # seconds for the whole download
MAX_BYTES = 8 * 1024 * 1024
RETRY_SECONDS = 60.0  # a failed URL is not tried again before this
CHUNK = 64 * 1024


class ArtTooLarge(Exception):
    pass


def download(url, path, timeout=TIMEOUT, deadline=DEADLINE, max_bytes=MAX_BYTES):
    """Fetch url into path, all or nothing: a partial file never lands at path."""
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.part"
    end = time.monotonic() + deadline
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > max_bytes:
                raise ArtTooLarge(f"{length} bytes, cap is {max_bytes}")
            size = 0
            with open(tmp, "wb") as out:
                while True:
                    if time.monotonic() > end:
                        raise TimeoutError(f"download took over {deadline:g}s")
                    # read1: whatever one recv brings. read(n) would wait for n
                    # bytes, and a host dripping a byte at a time never trips
                    # the per-read timeout nor reaches the deadline check.
                    chunk = response.read1(CHUNK)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise ArtTooLarge(f"over {max_bytes} bytes")
                    out.write(chunk)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def decode(path):
    with Image.open(path) as img:
        img.load()
        return img.copy()


class ArtLoader:
    def __init__(self, cache_dir, timeout=TIMEOUT, deadline=DEADLINE,
                 max_bytes=MAX_BYTES, retry_seconds=RETRY_SECONDS):
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.deadline = deadline
        self.max_bytes = max_bytes
        self.retry_seconds = retry_seconds
        self._lock = threading.Lock()
        self._url = None  # the art currently asked for
        self._img = None  # its decoded image, once ready
        self._ready = {}  # url -> image or None, filled by workers
        self._pending = set()
        self._failed = {}  # url -> monotonic time of the last failure

    def cache_path(self, url):
        return os.path.join(self.cache_dir, hashlib.sha1(url.encode()).hexdigest())

    def get(self, url):
        """The decoded art for url if it is ready, else None. Never blocks."""
        if not url or not url.startswith(("file://", "http://", "https://")):
            self._url = self._img = None
            return None
        if url != self._url:
            self._url, self._img = url, None
        if self._img is not None:
            return self._img
        with self._lock:
            if url in self._ready:
                self._img = self._ready.pop(url)
                if self._img is None:
                    self._failed[url] = time.monotonic()
                return self._img
            if url in self._pending:
                return None
            failed = self._failed.get(url)
            if failed is not None and time.monotonic() - failed < self.retry_seconds:
                return None
            self._pending.add(url)
        threading.Thread(target=self._work, args=(url,), name="ragnaros-art",
                         daemon=True).start()
        return None

    def _work(self, url):
        img = None
        try:
            if url.startswith("file://"):
                path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
            else:
                path = self.cache_path(url)
                if not os.path.exists(path):
                    os.makedirs(self.cache_dir, exist_ok=True)
                    download(url, path, self.timeout, self.deadline, self.max_bytes)
            img = decode(path)
        except Exception as error:
            print(f"ragnaros: album art load failed: {error}", file=sys.stderr)
        with self._lock:
            self._pending.discard(url)
            self._ready[url] = img
            # only the art someone may still ask for is kept around
            for stale in [u for u in self._ready if u not in (url, self._url)]:
                del self._ready[stale]
