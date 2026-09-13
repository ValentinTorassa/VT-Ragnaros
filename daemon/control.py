"""Unix socket control channel for ragnarosd.

One request per connection: a single command line in, one reply line
out. Kept synchronous and non-blocking so the daemon's single loop can
serve it between USB polls, and 0600 so only the session owner can
drive the deck.
"""
import json
import os
import select
import shlex
import socket


def socket_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime and os.path.isdir(runtime):
        return os.path.join(runtime, "ragnaros.sock")
    return os.path.join(
        os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
        "ragnaros", "control.sock")


class Control:
    def __init__(self, path=None):
        self.path = path or socket_path()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if os.path.exists(self.path):
            os.unlink(self.path)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(self.path)
        os.chmod(self.path, 0o600)
        self.sock.listen(8)
        self.sock.setblocking(False)
        self.subscribers = []

    def close(self):
        for conn, _ in self.subscribers:
            try:
                conn.close()
            except OSError:
                pass
        self.subscribers = []
        try:
            self.sock.close()
        finally:
            try:
                os.unlink(self.path)
            except OSError:
                pass

    def serve(self, handler, budget=8):
        """Answer up to `budget` pending requests, then return.

        A handler that returns `_stream` keeps its connection: the client
        becomes a subscriber and every later broadcast() reaches it.
        """
        self.reap()
        for _ in range(budget):
            try:
                conn, _ = self.sock.accept()
            except (BlockingIOError, OSError):
                return
            conn.settimeout(0.5)
            keep = False
            try:
                request = conn.recv(8192).decode("utf-8", "replace").strip()
                reply = handler(shlex.split(request)) if request else {
                    "ok": False, "error": "empty request"}
            except Exception as error:  # never let a client kill the daemon
                reply = {"ok": False, "error": str(error)}
            options = reply.pop("_stream", None) if isinstance(reply, dict) else None
            try:
                conn.sendall((json.dumps(reply) + "\n").encode())
                keep = options is not None
            except OSError:
                keep = False
            if keep:
                conn.setblocking(False)
                self.subscribers.append((conn, options))
            else:
                conn.close()

    def reap(self):
        """Drop subscribers that hung up - a dead client must release its grab."""
        if not self.subscribers:
            return
        try:
            readable, _, _ = select.select([c for c, _ in self.subscribers], [], [], 0)
        except (OSError, ValueError):
            readable = [c for c, _ in self.subscribers]
        dead = set()
        for conn in readable:
            try:
                if not conn.recv(4096):  # EOF
                    dead.add(conn)
            except BlockingIOError:
                pass
            except OSError:
                dead.add(conn)
        if not dead:
            return
        alive = []
        for conn, options in self.subscribers:
            if conn in dead:
                try:
                    conn.close()
                except OSError:
                    pass
            else:
                alive.append((conn, options))
        self.subscribers = alive

    def broadcast(self, event):
        """Push one event line to every subscriber; drop the ones that died."""
        if not self.subscribers:
            return
        payload = (json.dumps(event) + "\n").encode()
        alive = []
        for conn, options in self.subscribers:
            try:
                conn.sendall(payload)
                alive.append((conn, options))
            except (BlockingIOError, OSError):
                try:
                    conn.close()
                except OSError:
                    pass
        self.subscribers = alive

    def grabbed(self):
        """True while a subscriber asked to own the deck's inputs."""
        return any(options.get("grab") for _, options in self.subscribers)


def stream(argv, path=None, timeout=None):
    """Client side: send one command, then yield every pushed event line."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(path or socket_path())
        sock.sendall((" ".join(shlex.quote(a) for a in argv) + "\n").encode())
        buffer = b""
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if line.strip():
                    yield json.loads(line.decode())


def request(argv, path=None, timeout=2.0):
    """Client side: send one command, return the decoded reply."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(path or socket_path())
        sock.sendall((" ".join(shlex.quote(a) for a in argv) + "\n").encode())
        chunks = []
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            chunks.append(chunk)
            if chunks[-1].endswith(b"\n"):
                break
    return json.loads(b"".join(chunks).decode() or "{}")
