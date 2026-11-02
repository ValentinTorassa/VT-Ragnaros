"""Review what Jev said about Claude Code stops, from the hook's decision log.

  ragnaros-claude-hook review [--all] [-n N]   stops where Jev and the hook disagree, newest first
  ragnaros-claude-hook label ID CLASS          record the right class for one stop:
                                               waiting, finished or stuck
  ragnaros-claude-hook eval                    the hook vs Jev on the labeled stops,
                                               errors and latency

The log ($XDG_STATE_HOME/ragnaros/claude-jev.jsonl, or $RAGNAROS_JEV_LOG) is
append-only; labels go to claude-jev-labels.jsonl next to it, and the last
label for a stop wins. Nothing here calls Jev.
"""
import argparse
import json
import os
import sys
import time
from collections import Counter

from . import claude_hook

THRESHOLDS = (0.3, 0.5, 0.7, 0.9)


def labels_file(log):
    root, _ = os.path.splitext(log)
    return root + "-labels.jsonl"


def read_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except FileNotFoundError:
        pass
    return rows


def read_labels(path):
    return {r["id"]: r["label"] for r in read_jsonl(path)
            if r.get("id") and r.get("label") in claude_hook.CLASSES}


def answered(entries):
    return [e for e in entries if isinstance(e.get("jev"), dict) and isinstance(e.get("hook"), dict)]


def disagrees(entry):
    return entry["jev"].get("class") != entry["hook"].get("class")


def line_for(entry, label=None):
    j, p = entry["jev"], entry["jev"].get("p") or {}
    head = (f"{entry.get('id')}  {str(entry.get('time', ''))[:16].replace('T', ' ')}  "
            f"{entry.get('project') or '?'}  hook {entry['hook'].get('class')} -> "
            f"jev {j.get('class')} {p.get(j.get('class'), 0):.2f}")
    if label:
        head += f"  [label: {label}]"
    message = ((entry.get("state") or {}).get("message") or "").strip()
    tail = message if len(message) <= 160 else "…" + message[-160:]
    return f"{head}\n    {tail}"


def review(args, log):
    entries = answered(read_jsonl(log))
    labels = read_labels(labels_file(log))
    shown = entries if args.all else [e for e in entries if disagrees(e)]
    print(f"{len(entries)} stops answered by Jev, {sum(map(disagrees, entries))} where it "
          f"disagrees with the hook, {len(labels)} labeled - {log}")
    for entry in list(reversed(shown))[:args.n]:
        print(line_for(entry, labels.get(entry.get("id"))))
    if shown:
        print("\nlabel one with: ragnaros-claude-hook label ID waiting|finished|stuck")
    return 0


def label(args, log):
    if args.cls not in claude_hook.CLASSES:
        print(f"the class is one of: {', '.join(claude_hook.CLASSES)}", file=sys.stderr)
        return 2
    if not any(e.get("id") == args.id for e in read_jsonl(log)):
        print(f"no stop {args.id} in {log}", file=sys.stderr)
        return 1
    claude_hook.append(labels_file(log), {"id": args.id, "label": args.cls,
                                          "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    print(f"{args.id}: {args.cls}")
    return 0


def percentile(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def on_mode(entry, threshold):
    """What `on` would have shown with this jev_min."""
    j = entry["jev"]
    if (j.get("p") or {}).get(j.get("class"), 0) >= threshold:
        return j.get("class")
    return entry["hook"].get("class")


def score(pairs):
    """pairs of (decided, right) classes -> accuracy and the loudness errors."""
    loud = claude_hook.LOUD
    return {"right": sum(d == r for d, r in pairs),
            "missed": sum(r in loud and d not in loud for d, r in pairs),
            "false_alarms": sum(r not in loud and d in loud for d, r in pairs)}


def evaluate(args, log):
    entries = read_jsonl(log)
    done = answered(entries)
    errors = Counter((e.get("error") or "").split(":")[0] for e in entries if e.get("error"))
    ms = [e["jev"]["ms"] for e in done if isinstance(e["jev"].get("ms"), (int, float))]
    print(f"{len(entries)} stops logged, {len(done)} answered by Jev - {log}")
    if ms:
        print(f"latency: p50 {percentile(ms, 0.5)} ms, p95 {percentile(ms, 0.95)} ms, "
              f"max {max(ms)} ms")
    for kind, n in errors.most_common():
        print(f"error: {n:4d}  {kind}")
    labels = read_labels(labels_file(log))
    rows = [(e, labels[e["id"]]) for e in done if e.get("id") in labels]
    if not rows:
        print("\nno labeled stops yet: `ragnaros-claude-hook review`, then `label ID CLASS`")
        return 0
    n = len(rows)
    print(f"\n{n} labeled: " + ", ".join(f"{c} {sum(r == c for _, r in rows)}"
                                         for c in claude_hook.CLASSES))
    print(f"{'':12} {'right':>7} {'missed':>7} {'false alarms':>13}")

    def show(name, pairs):
        s = score(pairs)
        print(f"{name:12} {s['right']:4d}/{n:<2d} {s['missed']:7d} {s['false_alarms']:13d}")

    show("hook today", [(e["hook"].get("class"), r) for e, r in rows])
    show("jev", [(e["jev"].get("class"), r) for e, r in rows])
    for t in THRESHOLDS:
        show(f"on, min {t}", [(on_mode(e, t), r) for e, r in rows])
    print("\nmissed = waiting or stuck shown as a quiet toast; false alarm = finished held as an alert")
    print("\njev class by label (rows: label, columns: jev)")
    print(f"{'':10}" + "".join(f"{c:>10}" for c in claude_hook.CLASSES))
    for right in claude_hook.CLASSES:
        counts = Counter(e["jev"].get("class") for e, r in rows if r == right)
        print(f"{right:10}" + "".join(f"{counts[c]:10d}" for c in claude_hook.CLASSES))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="ragnaros-claude-hook", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--log", help="the decision log (default: claude-jev.jsonl in the state dir)")
    sub = parser.add_subparsers(dest="command", metavar="command")
    p = sub.add_parser("review", parents=[common], help="stops where Jev and the hook disagree")
    p.add_argument("--all", action="store_true", help="every answered stop, not only disagreements")
    p.add_argument("-n", type=int, default=20, help="how many, newest first (default 20)")
    p = sub.add_parser("label", parents=[common], help="record the right class for one stop")
    p.add_argument("id")
    p.add_argument("cls", metavar="CLASS", help="waiting, finished or stuck")
    sub.add_parser("eval", parents=[common], help="the hook vs Jev on the labeled stops")
    args = parser.parse_args(argv)
    log = getattr(args, "log", None) or claude_hook.log_file()
    run = {"review": review, "label": label, "eval": evaluate}.get(args.command)
    if not run:
        parser.print_help()
        return 0
    return run(args, log)


if __name__ == "__main__":
    sys.exit(main())
