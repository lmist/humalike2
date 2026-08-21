#!/usr/bin/env python3
"""Summarize a shadow-proxy golden dataset (JSONL) — divergences by path, latency,
and bubble-stream comparison per thread. Usage: report.py [file ...]
(default: newest tools/shadow/golden/*.jsonl)."""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def load(paths):
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)


def main(argv):
    paths = [Path(a) for a in argv[1:]]
    if not paths:
        golden = sorted((Path(__file__).resolve().parent / "golden").glob("*.jsonl"))
        if not golden:
            print("no dataset yet")
            return 1
        paths = [golden[-1]]
    recs = list(load(paths))
    http = [r for r in recs if r.get("kind") == "http"]
    ws = [r for r in recs if r.get("kind") == "ws"]
    print(f"dataset: {', '.join(str(p) for p in paths)}\nrecords: {len(recs)} (http {len(http)}, ws frames {len(ws)})\n")

    by_path = defaultdict(list)
    for r in http:
        by_path[r["request"]["path"]].append(r)
    print(f"{'path':58} {'n':>3} {'mirr':>4} {'div':>3} {'loc ms':>7} {'prod ms':>8}  divergence kinds")
    for path, rs in sorted(by_path.items()):
        mirrored = [r for r in rs if r.get("prod")]
        div = [r for r in mirrored if (r.get("diff") or {}).get("diverged")]
        kinds = defaultdict(int)
        for r in div:
            for k in r["diff"]["diverged"]:
                kinds[k] += 1
        lm = statistics.median(r["local"]["latency_ms"] for r in rs if r.get("local", {}).get("latency_ms") is not None) if rs else 0
        pm = statistics.median(r["prod"]["latency_ms"] for r in mirrored if r["prod"].get("latency_ms") is not None) if mirrored else 0
        print(f"{path:58} {len(rs):3d} {len(mirrored):4d} {len(div):3d} {lm:7.0f} {pm:8.0f}  {dict(kinds) if kinds else ''}")

    decided = [r for r in http if r["request"]["path"].endswith("/submit_messages") and r.get("prod") and r["prod"].get("body")]
    if decided:
        agree = sum(1 for r in decided if r["diff"].get("decision", [0, 1])[0] == r["diff"]["decision"][1])
        print(f"\ndecision agreement: {agree}/{len(decided)}")
        for r in decided:
            d = r["diff"].get("decision", [None, None])
            if d[0] != d[1]:
                msgs = r["request"]["body"].get("messages") or []
                last = msgs[-1] if msgs else {}
                print(f"  #{r['seq']} local={d[0]} prod={d[1]}  last msg: {last.get('sender')}: {str(last.get('content'))[:80]!r}")

    responded = [r for r in http if r["request"]["path"].endswith("/respond") and r.get("prod") and r["prod"].get("body")]
    if responded:
        print("\nrespond (bubble split):")
        for r in responded:
            sc = r["diff"].get("scheduled_count", [None, None])
            flag = "" if sc[0] == sc[1] else "  <-- count differs"
            print(f"  #{r['seq']} local {sc[0]} / prod {sc[1]} bubbles; superseded {r['diff'].get('superseded')}{flag}")
            cont = r["diff"].get("scheduled_contents") or [[], []]
            for side, lst in zip(("local", "prod"), cont):
                for i, c in enumerate(lst):
                    print(f"      {side}[{i}] {str(c)[:90]!r}")

    if ws:
        print("\nws frames per thread:")
        per = defaultdict(lambda: defaultdict(list))
        for f in ws:
            key = f.get("thread_local") or f.get("thread_seen") or "?"
            per[key][f["side"]].append(f)
        for tid, sides in per.items():
            line = [f"  {tid[:8]}:"]
            for side in ("local", "prod"):
                frames = sides.get(side, [])
                msgs = [f for f in frames if f.get("type") == "turn_taking.message"]
                gaps = [round(b["recv_offset_ms"] - a["recv_offset_ms"]) for a, b in zip(msgs, msgs[1:])]
                line.append(f"{side}: {len(frames)} frames, {len(msgs)} messages, gaps {gaps}")
            print(" | ".join(line))
    errs = [r for r in http if r.get("prod") and r["prod"].get("error")]
    if errs:
        print(f"\nprod errors: {len(errs)}")
        for r in errs[:10]:
            print(f"  #{r['seq']} {r['request']['path']}: {r['prod']['error'][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
