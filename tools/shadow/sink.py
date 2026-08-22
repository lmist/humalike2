#!/usr/bin/env python3
"""JSONL → SQLite sink for the shadow-proxy golden dataset.

The proxy appends raw records to ``golden/<date>.jsonl``; this tails those
files into a queryable SQLite database (``golden/shadow.sqlite`` by default).
Idempotent: each (file, line number) is ingested once, so it can be re-run,
restarted, or left following indefinitely while the proxy keeps running.

    tools/shadow/sink.py                 # backfill every golden/*.jsonl, then exit
    tools/shadow/sink.py --follow        # backfill, then keep tailing (1 s poll)
    tools/shadow/sink.py --db path.sqlite file.jsonl ...

Tables
  exchanges   one row per HTTP request: request, local response, prod response,
              latencies, request-ids, decision/bubble columns, diff + diverged flags
  ws_frames   one row per WebSocket frame (side = local|prod), with recv offset,
              type, content, and the full frame
  ws_events   socket open/close/error per side with close codes
  threads     local thread id ↔ production thread id (learned from open_thread pairs)
  ingest      bookkeeping: (file, line) already loaded

Views
  decisions   submit_messages pairs side by side (last message, both decisions)
  bubbles     respond pairs: bubble counts and contents per side
  divergent   every exchange whose diff flagged something
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest (
  file TEXT NOT NULL, line INTEGER NOT NULL, PRIMARY KEY (file, line));
CREATE TABLE IF NOT EXISTS exchanges (
  file TEXT NOT NULL, line INTEGER NOT NULL,
  seq INTEGER, ts TEXT, completed_at TEXT,
  method TEXT, path TEXT, query TEXT, request_body TEXT,
  thread_local TEXT, thread_prod TEXT,
  local_status INTEGER, local_latency_ms REAL, local_request_id TEXT, local_body TEXT, local_error TEXT,
  prod_status INTEGER, prod_latency_ms REAL, prod_request_id TEXT, prod_body TEXT, prod_error TEXT,
  prod_rewrites TEXT, mirrored INTEGER NOT NULL DEFAULT 0,
  decision_local TEXT, decision_prod TEXT,
  epoch_local INTEGER, epoch_prod INTEGER,
  bubbles_local INTEGER, bubbles_prod INTEGER,
  superseded_local INTEGER, superseded_prod INTEGER,
  diverged TEXT, diverged_any INTEGER NOT NULL DEFAULT 0, diff TEXT,
  PRIMARY KEY (file, line));
CREATE INDEX IF NOT EXISTS exchanges_path ON exchanges(path);
CREATE INDEX IF NOT EXISTS exchanges_thread ON exchanges(thread_local);
CREATE INDEX IF NOT EXISTS exchanges_div ON exchanges(diverged_any);
CREATE TABLE IF NOT EXISTS ws_frames (
  file TEXT NOT NULL, line INTEGER NOT NULL,
  ts TEXT, side TEXT, thread_local TEXT, thread_prod TEXT, thread_seen TEXT, open_seq INTEGER,
  type TEXT, recv_offset_ms REAL, message_id TEXT, position INTEGER, content TEXT, typing INTEGER,
  sent_at TEXT, frame TEXT,
  PRIMARY KEY (file, line));
CREATE INDEX IF NOT EXISTS ws_frames_thread ON ws_frames(thread_seen, side);
CREATE TABLE IF NOT EXISTS ws_events (
  file TEXT NOT NULL, line INTEGER NOT NULL,
  ts TEXT, side TEXT, event TEXT, thread_local TEXT, thread_prod TEXT, thread_seen TEXT, open_seq INTEGER,
  code INTEGER, reason TEXT, duration_ms REAL, error TEXT,
  PRIMARY KEY (file, line));
CREATE TABLE IF NOT EXISTS threads (
  thread_local TEXT PRIMARY KEY, thread_prod TEXT, opened_seq INTEGER, opened_at TEXT, file TEXT);
CREATE VIEW IF NOT EXISTS decisions AS
  SELECT seq, ts, thread_local, thread_prod,
         json_extract(request_body, '$.messages[#-1].sender')  AS sender,
         json_extract(request_body, '$.messages[#-1].content') AS last_message,
         decision_local, decision_prod, epoch_local, epoch_prod,
         local_latency_ms, prod_latency_ms,
         (decision_local IS NOT decision_prod) AS disagree
  FROM exchanges WHERE path LIKE '%/submit_messages' AND mirrored = 1;
CREATE VIEW IF NOT EXISTS bubbles AS
  SELECT seq, ts, thread_local, thread_prod,
         json_extract(request_body, '$.content') AS draft,
         bubbles_local, bubbles_prod, superseded_local, superseded_prod,
         json_extract(diff, '$.scheduled_contents[0]') AS contents_local,
         json_extract(diff, '$.scheduled_contents[1]') AS contents_prod,
         local_latency_ms, prod_latency_ms
  FROM exchanges WHERE path LIKE '%/respond' AND mirrored = 1;
CREATE VIEW IF NOT EXISTS divergent AS
  SELECT seq, ts, path, diverged, local_status, prod_status, decision_local, decision_prod,
         bubbles_local, bubbles_prod, prod_error
  FROM exchanges WHERE diverged_any = 1;
"""


def _j(v: Any) -> Optional[str]:
    return None if v is None else json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _thread_of(rec: dict) -> Optional[str]:
    body = (rec.get("request") or {}).get("body")
    if isinstance(body, dict) and isinstance(body.get("thread_id"), str):
        return body["thread_id"]
    lb = (rec.get("local") or {}).get("body")
    if isinstance(lb, dict) and isinstance(lb.get("thread"), dict):
        return lb["thread"].get("id")
    return None


def _bool(v: Any) -> Optional[int]:
    return None if v is None else int(bool(v))


def insert_http(cur: sqlite3.Cursor, file: str, line: int, rec: dict, prod_threads: dict) -> None:
    req, loc, prod, diff = rec.get("request") or {}, rec.get("local") or {}, rec.get("prod"), rec.get("diff") or {}
    lb, pb = loc.get("body"), (prod or {}).get("body")
    lbd, pbd = (lb if isinstance(lb, dict) else {}), (pb if isinstance(pb, dict) else {})
    tl = _thread_of(rec)
    tp = None
    if isinstance(pbd.get("thread"), dict):
        tp = pbd["thread"].get("id")
        if tl and tp:
            prod_threads[tl] = tp
            cur.execute("INSERT OR REPLACE INTO threads VALUES (?,?,?,?,?)", (tl, tp, rec.get("seq"), rec.get("ts"), file))
    tp = tp or prod_threads.get(tl or "")
    sc = diff.get("scheduled_count") or [None, None]
    sup = diff.get("superseded") or [None, None]
    cur.execute(
        "INSERT OR REPLACE INTO exchanges VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (file, line, rec.get("seq"), rec.get("ts"), rec.get("completed_at"),
         req.get("method"), req.get("path"), req.get("query"), _j(req.get("body")),
         tl, tp,
         loc.get("status"), loc.get("latency_ms"), (loc.get("headers") or {}).get("x-request-id"), _j(lb), loc.get("error"),
         (prod or {}).get("status"), (prod or {}).get("latency_ms"), ((prod or {}).get("headers") or {}).get("x-request-id"),
         _j(pb), (prod or {}).get("error"), _j((prod or {}).get("request_rewrites")), int(prod is not None),
         lbd.get("decision"), pbd.get("decision"), lbd.get("turn_epoch"), pbd.get("turn_epoch"),
         sc[0], sc[1], _bool(sup[0]), _bool(sup[1]),
         _j(diff.get("diverged")), int(bool(diff.get("diverged"))), _j(diff) if diff else None))


def insert_ws(cur: sqlite3.Cursor, file: str, line: int, rec: dict) -> None:
    fr = rec.get("frame") or {}
    data = fr.get("data") if isinstance(fr, dict) and isinstance(fr.get("data"), dict) else {}
    cur.execute(
        "INSERT OR REPLACE INTO ws_frames VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (file, line, rec.get("ts"), rec.get("side"), rec.get("thread_local"), rec.get("thread_prod"), rec.get("thread_seen"),
         rec.get("open_seq"), rec.get("type"), rec.get("recv_offset_ms"), data.get("message_id"), data.get("position"),
         data.get("content"), _bool(data.get("typing")) if "typing" in data else None, data.get("sent_at"), _j(fr)))


def insert_ws_event(cur: sqlite3.Cursor, file: str, line: int, rec: dict) -> None:
    cur.execute(
        "INSERT OR REPLACE INTO ws_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (file, line, rec.get("ts"), rec.get("side"), rec.get("event"), rec.get("thread_local"), rec.get("thread_prod"),
         rec.get("thread_seen"), rec.get("open_seq"), rec.get("code"), rec.get("reason"), rec.get("duration_ms"), rec.get("error")))


def ingest_file(db: sqlite3.Connection, path: Path, prod_threads: dict) -> int:
    """Load every not-yet-ingested line of ``path``. Returns rows added."""
    cur = db.cursor()
    done = {r[0] for r in cur.execute("SELECT line FROM ingest WHERE file = ?", (str(path),))}
    added = 0
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            if n in done:
                continue
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue  # a partially written last line: retry on the next pass
            kind = rec.get("kind")
            if kind == "http":
                insert_http(cur, str(path), n, rec, prod_threads)
            elif kind == "ws":
                insert_ws(cur, str(path), n, rec)
            elif kind == "ws_event":
                insert_ws_event(cur, str(path), n, rec)
            cur.execute("INSERT OR IGNORE INTO ingest VALUES (?,?)", (str(path), n))
            added += 1
    db.commit()
    return added


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path))
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def run(db_path: Path, files: Iterable[Path], follow: bool) -> int:
    db = open_db(db_path)
    prod_threads = {r[0]: r[1] for r in db.execute("SELECT thread_local, thread_prod FROM threads")}
    files = list(files)
    while True:
        if not files:
            files = sorted(GOLDEN.glob("*.jsonl"))
        total = 0
        for f in files:
            if f.exists():
                total += ingest_file(db, f, prod_threads)
        if total:
            n = db.execute("SELECT (SELECT count(*) FROM exchanges), (SELECT count(*) FROM ws_frames)").fetchone()
            print(f"{time.strftime('%H:%M:%S')} +{total} rows → exchanges={n[0]} ws_frames={n[1]}", flush=True)
        if not follow:
            break
        time.sleep(1.0)
        files = []  # re-glob so a new day's file is picked up
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, help="JSONL files (default: golden/*.jsonl)")
    ap.add_argument("--db", type=Path, default=GOLDEN / "shadow.sqlite")
    ap.add_argument("--follow", action="store_true", help="keep tailing after the backfill")
    a = ap.parse_args(argv[1:])
    return run(a.db, a.files, a.follow)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
