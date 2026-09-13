#!/usr/bin/env python3
"""Claude Code hook: tell the deck when a session stops working.

Register it as a `Stop` hook and the strip shows "Claude terminó", the
project and the last thing Claude said, for a few seconds - then it goes
back to the GIFs, the dashboard or whatever it was showing.

  cat hook.json | python3 tools/claude_hook.py

  RAGNAROS_CLAUDE_HOOK_MODE=alert   hold the notice until a key is pressed
  RAGNAROS_CLAUDE_HOOK_SECONDS=12   how long the toast stays (default 8)

Never fails the session: every error exits 0 quietly.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "daemon"))

TAIL_BYTES = 256 * 1024
MAX_BODY = 140
MODE = os.environ.get("RAGNAROS_CLAUDE_HOOK_MODE", "toast")
SECONDS = os.environ.get("RAGNAROS_CLAUDE_HOOK_SECONDS", "8")


def last_assistant_text(path):
    """The last thing Claude said, from the tail of the transcript."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - TAIL_BYTES))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content") or []
        if isinstance(content, str):
            text = content
        else:
            text = " ".join(part.get("text", "") for part in content
                            if isinstance(part, dict) and part.get("type") == "text")
        text = " ".join(text.split())
        if text:
            return text[:MAX_BODY] + ("…" if len(text) > MAX_BODY else "")
    return ""


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    if payload.get("stop_hook_active"):
        return 0  # we are inside a stop hook continuation, not a fresh finish
    project = os.path.basename(payload.get("cwd") or os.getcwd()) or "claude"
    event = payload.get("hook_event_name") or "Stop"
    summary = "Claude espera" if event == "Notification" else "Claude terminó"
    body = last_assistant_text(payload.get("transcript_path") or "")
    detail = f"{project} · {body}" if body else project
    command = ["alert"] if MODE == "alert" else ["toast", f"--seconds={SECONDS}"]
    try:
        import control

        control.request(command + [summary, detail, "--app=claude"], timeout=1.0)
    except Exception:
        pass  # no deck, no daemon, no problem
    return 0


if __name__ == "__main__":
    sys.exit(main())
