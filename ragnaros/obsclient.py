"""Minimal OBS WebSocket v5 client using only the Python stdlib.

Protocol: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
Supports Hello/Identify (with password auth), requests, and server pings.
"""
import base64
import hashlib
import json
import os
import socket
import struct

DEFAULT_CONFIG = os.path.expanduser("~/.config/ragnaros/obs.json")


def load_config():
    try:
        with open(DEFAULT_CONFIG) as f:
            cfg = json.load(f)
        return (cfg.get("host", "127.0.0.1"), int(cfg.get("port", 4455)),
                cfg.get("password", ""))
    except (OSError, ValueError):
        return ("127.0.0.1", 4455, "")


class ObsError(Exception):
    pass


def _frame_encode(payload, opcode=1):
    data = payload.encode()
    length = len(data)
    mask = b"\x00\x00\x00\x00"  # zero mask keeps payload unchanged
    if length < 126:
        header = struct.pack("!BB", 0x80 | opcode, 0x80 | length)
    elif length < 65536:
        header = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, length)
    else:
        header = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, length)
    return header + mask + data


class ObsClient:
    def __init__(self, host="127.0.0.1", port=4455, password="", timeout=2.0):
        self.addr = (host, port)
        self.password = password or load_config()[2]
        self.timeout = timeout
        self.sock = None
        self._buf = b""
        self._req_id = 0

    # -- websocket plumbing ------------------------------------------------
    def _connect(self):
        self.sock = socket.create_connection(self.addr, timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET / HTTP/1.1\r\nHost: {self.addr[0]}:{self.addr[1]}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ObsError("connection closed during handshake")
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise ObsError("websocket upgrade refused")
        self._buf = response.split(b"\r\n\r\n", 1)[1]

    def _recv_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ObsError("connection closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _read_message(self):
        while True:
            b1, b2 = self._recv_exact(2)
            opcode = b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            payload = self._recv_exact(length)
            if opcode == 0x9:  # ping -> pong
                self.sock.sendall(_frame_encode(payload, opcode=10))
                continue
            if opcode == 0x8:  # close
                raise ObsError("server closed connection")
            if opcode in (0x1, 0x2):
                return json.loads(payload.decode())

    def _send(self, obj):
        self.sock.sendall(_frame_encode(json.dumps(obj)))

    # -- obs protocol ------------------------------------------------------
    def connect(self):
        self._connect()
        hello = self._read_message()
        if hello.get("op") != 0:
            raise ObsError("expected Hello")
        data = {"rpcVersion": 1, "eventSubscriptions": 0}
        auth = hello.get("d", {}).get("authentication")
        if auth:
            secret = base64.b64encode(hashlib.sha256(
                self.password.encode() + auth["salt"].encode()).digest()).decode()
            challenge = auth["challenge"]
            data["authentication"] = base64.b64encode(hashlib.sha256(
                secret.encode() + challenge.encode()).digest()).decode()
        self._send({"op": 1, "d": data})
        reply = self._read_message()
        if reply.get("op") != 2:
            raise ObsError(f"identify failed: {reply}")

    def request(self, request_type, request_data=None):
        self._req_id += 1
        rid = f"ragnaros-{self._req_id}"
        self._send({"op": 6, "d": {
            "requestType": request_type,
            "requestId": rid,
            "requestData": request_data or {},
        }})
        while True:
            msg = self._read_message()
            if msg.get("op") == 7 and msg.get("d", {}).get("requestId") == rid:
                d = msg["d"]
                if d.get("requestStatus", {}).get("result") is not True:
                    raise ObsError(f"{request_type}: {d.get('requestStatus')}")
                return d.get("responseData", {})

    def close(self):
        if self.sock:
            try:
                self.sock.sendall(_frame_encode(b"", opcode=8))
                self.sock.close()
            except OSError:
                pass
            self.sock = None


def status():
    """Return {'recording':bool,'streaming':bool,'scenes':[names]} or raise."""
    client = ObsClient()
    try:
        client.connect()
        rec = client.request("GetRecordStatus")
        stm = client.request("GetStreamStatus")
        try:
            scenes = [s["sceneName"] for s in
                      client.request("GetSceneList").get("scenes", [])]
        except ObsError:
            scenes = []
        return {
            "recording": bool(rec.get("outputActive")),
            "paused": bool(rec.get("outputPaused")),
            "streaming": bool(stm.get("outputActive")),
            "scenes": scenes,
        }
    finally:
        client.close()


def command(name, data=None):
    client = ObsClient()
    try:
        client.connect()
        return client.request(name, data)
    finally:
        client.close()
