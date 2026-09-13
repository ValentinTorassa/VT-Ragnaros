import os
import time

import control


def test_request_round_trip(tmp_path):
    path = str(tmp_path / "test.sock")
    server = control.Control(path)
    seen = []

    def handler(argv):
        seen.append(argv)
        return {"ok": True, "echo": argv}

    try:
        assert oct(os.stat(path).st_mode)[-3:] == "600"
        import threading

        replies = []
        client = threading.Thread(
            target=lambda: replies.append(control.request(["toast", "hola mundo"], path)))
        client.start()
        for _ in range(200):  # the daemon serves between USB polls
            server.serve(handler)
            if replies:
                break
        client.join(2)
        assert seen == [["toast", "hola mundo"]]
        assert replies == [{"ok": True, "echo": ["toast", "hola mundo"]}]
    finally:
        server.close()
    assert not os.path.exists(path)


def test_handler_errors_come_back_as_a_reply(tmp_path):
    path = str(tmp_path / "boom.sock")
    server = control.Control(path)
    try:
        import threading

        replies = []
        client = threading.Thread(
            target=lambda: replies.append(control.request(["explode"], path)))
        client.start()
        for _ in range(200):
            server.serve(lambda argv: 1 / 0)
            if replies:
                break
        client.join(2)
        assert replies and replies[0]["ok"] is False
        assert "division" in replies[0]["error"]
    finally:
        server.close()


def stream_client(path, argv, received, ready):
    events = control.stream(argv, path, timeout=3.0)
    for event in events:
        received.append(event)
        ready.set()


def test_a_watcher_stays_connected_and_receives_broadcasts(tmp_path):
    import threading

    path = str(tmp_path / "watch.sock")
    server = control.Control(path)
    received, ready = [], threading.Event()
    try:
        client = threading.Thread(target=stream_client,
                                  args=(path, ["watch", "--grab"], received, ready),
                                  daemon=True)
        client.start()
        for _ in range(200):
            server.serve(lambda argv: {"ok": True, "watching": True,
                                       "_stream": {"grab": "--grab" in argv}})
            if ready.wait(0.01):
                break
        assert received == [{"ok": True, "watching": True}]
        assert server.grabbed() is True  # the client owns the deck's inputs
        server.broadcast({"type": "key", "index": 3})
        for _ in range(200):
            if len(received) > 1:
                break
            time.sleep(0.01)
        assert received[1] == {"type": "key", "index": 3}
    finally:
        server.close()


def test_a_dead_watcher_releases_its_grab(tmp_path):
    import socket as socketlib

    path = str(tmp_path / "dead.sock")
    server = control.Control(path)
    try:
        client = socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM)
        client.connect(path)
        client.sendall(b"watch --grab\n")
        for _ in range(200):
            server.serve(lambda argv: {"ok": True, "_stream": {"grab": True}})
            if server.subscribers:
                break
        assert server.grabbed() is True
        client.close()
        for _ in range(200):
            server.reap()
            if not server.subscribers:
                break
            time.sleep(0.01)
        assert server.grabbed() is False
    finally:
        server.close()
