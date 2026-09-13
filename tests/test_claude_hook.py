import importlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import claude_hook  # noqa: E402
import control  # noqa: E402


def load(monkeypatch, **env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return importlib.reload(claude_hook)


def transcript(tmp_path, entries):
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries))
    return str(path)


def assistant(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def run(monkeypatch, hook, payload):
    sent = []
    monkeypatch.setattr(control, "request", lambda argv, **kw: sent.append(argv))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert hook.main() == 0
    return sent


def test_reads_the_last_thing_claude_said(tmp_path, monkeypatch):
    hook = load(monkeypatch)
    path = transcript(tmp_path, [
        assistant("primero"),
        {"type": "user", "message": {"content": "y ahora?"}},
        assistant("Listo: arreglé el orden de los paneles."),
    ])
    assert hook.last_assistant_text(path) == "Listo: arreglé el orden de los paneles."


def test_a_long_answer_is_truncated(tmp_path, monkeypatch):
    hook = load(monkeypatch)
    path = transcript(tmp_path, [assistant("x" * 500)])
    text = hook.last_assistant_text(path)
    assert len(text) == hook.MAX_BODY + 1 and text.endswith("…")


def test_a_missing_transcript_is_not_an_error(monkeypatch):
    hook = load(monkeypatch)
    assert hook.last_assistant_text("/does/not/exist") == ""


def test_stop_sends_a_transient_toast(tmp_path, monkeypatch):
    hook = load(monkeypatch)
    sent = run(monkeypatch, hook, {"hook_event_name": "Stop", "cwd": "/tmp/VT-Ragnaros",
                                   "transcript_path": transcript(tmp_path, [assistant("ok")])})
    assert sent[0][0] == "toast"
    assert sent[0][1] == "--seconds=8"
    assert "Claude terminó" in sent[0]
    assert "VT-Ragnaros · ok" in sent[0]


def test_alert_mode_holds_the_strip(tmp_path, monkeypatch):
    hook = load(monkeypatch, RAGNAROS_CLAUDE_HOOK_MODE="alert")
    sent = run(monkeypatch, hook, {"hook_event_name": "Stop", "cwd": "/tmp/p"})
    assert sent[0][0] == "alert"
    load(monkeypatch, RAGNAROS_CLAUDE_HOOK_MODE="toast")  # leave the module clean


def test_a_notification_hook_says_it_is_waiting(monkeypatch):
    hook = load(monkeypatch)
    sent = run(monkeypatch, hook, {"hook_event_name": "Notification", "cwd": "/tmp/p"})
    assert "Claude espera" in sent[0]


def test_a_stop_continuation_stays_quiet(monkeypatch):
    hook = load(monkeypatch)
    assert run(monkeypatch, hook, {"hook_event_name": "Stop", "stop_hook_active": True}) == []


def test_a_dead_daemon_never_fails_the_session(monkeypatch):
    hook = load(monkeypatch)

    def boom(argv, **kwargs):
        raise ConnectionRefusedError("no daemon")

    monkeypatch.setattr(control, "request", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert hook.main() == 0
