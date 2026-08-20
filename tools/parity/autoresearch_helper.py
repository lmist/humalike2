#!/usr/bin/env python3
"""Autoresearch experiment-log helper (init / log / evaluate / status / summary).

Implements the autoresearch pattern's structured JSONL logging and MAD-based
confidence scoring for the API parity loop (bead hum-4ko6, spec/07 phase 8).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path


def _read(jsonl: Path) -> tuple[dict | None, list[dict]]:
    config, rows = None, []
    if jsonl.exists():
        for line in jsonl.read_text().splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("type") == "config":
                config = obj
            else:
                rows.append(obj)
    return config, rows


def _append(jsonl: Path, obj: dict) -> None:
    with jsonl.open("a") as f:
        f.write(json.dumps(obj, separators=(",", ":")) + "\n")


def _confidence(rows: list[dict], value: float, direction: str) -> float | None:
    """|delta from best| / MAD of kept metrics; advisory only."""
    kept = [r["metric"] for r in rows if r.get("status") == "keep"]
    if len(kept) < 3:
        return None
    med = statistics.median(kept)
    mad = statistics.median(abs(k - med) for k in kept) or 1e-9
    best = min(kept) if direction == "lower" else max(kept)
    return abs(value - best) / mad


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["init", "log", "evaluate", "status", "summary"])
    p.add_argument("--jsonl", type=Path, required=True)
    p.add_argument("--name")
    p.add_argument("--metric-name")
    p.add_argument("--metric", type=float)
    p.add_argument("--metrics", default=None)
    p.add_argument("--direction", choices=["lower", "higher"], default="lower")
    p.add_argument("--commit")
    p.add_argument("--status", dest="run_status")
    p.add_argument("--description")
    p.add_argument("--asi", default="{}")
    args = p.parse_args()

    config, rows = _read(args.jsonl)

    if args.command == "init":
        _append(args.jsonl, {"type": "config", "name": args.name,
                             "metricName": args.metric_name, "metricUnit": "count",
                             "bestDirection": args.direction})
        print(f"initialized {args.jsonl}")
        return 0

    if args.command == "log":
        entry = {
            "run": len(rows) + 1,
            "commit": args.commit or "0000000",
            "metric": args.metric,
            "status": args.run_status,
            "description": args.description or "",
            "timestamp": int(time.time() * 1000),
            "segment": 0,
            "confidence": _confidence(rows, args.metric, args.direction),
            "asi": json.loads(args.asi),
        }
        if args.metrics:
            entry["metrics"] = json.loads(args.metrics)
        _append(args.jsonl, entry)
        print(json.dumps(entry))
        return 0

    if args.command == "evaluate":
        kept = [r["metric"] for r in rows if r.get("status") == "keep"]
        best = (min(kept) if args.direction == "lower" else max(kept)) if kept else None
        improved = best is None or (
            args.metric < best if args.direction == "lower" else args.metric > best)
        print(json.dumps({
            "decision": "keep" if improved else "discard",
            "best": best,
            "delta_from_best": None if best is None else args.metric - best,
            "confidence": _confidence(rows, args.metric, args.direction),
        }))
        return 0

    kept = [r for r in rows if r.get("status") == "keep"]
    summary = {
        "config": config,
        "experiments": len(rows),
        "kept": len(kept),
        "best": (min if (config or {}).get("bestDirection", "lower") == "lower" else max)(
            (r["metric"] for r in kept), default=None),
        "latest": rows[-1] if rows else None,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
