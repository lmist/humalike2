"""Shadow proxy — serve from the recreation, mirror to production, record both.

The Hermes plugin (or any client) points HUMALIKE_API_URL at this process.
For every HTTP request:

  1. it is forwarded verbatim to the LOCAL recreation and that response is what
     the client gets back (the client's contract is untouched);
  2. a copy is queued for PRODUCTION, sent with the production key, in arrival
     order, with local resource ids / turn epochs remapped to production's;
  3. the request, both responses, latencies and a structural diff are appended
     as one JSON line to the golden dataset.

WebSocket: the recreation's ``realtime.connect_url`` is rewritten to point at
this proxy, which bridges the client to the recreation socket frame-for-frame
(recording each frame) and, separately, opens production's grant and records
its frames too. So the dataset holds both sides' bubble streams and timings.

Never recorded: Authorization headers, keys, grant tokens (redacted).

Env:
  SHADOW_HOST / SHADOW_PORT        bind (127.0.0.1 / 8081)
  SHADOW_LOCAL_URL                 recreation origin (http://127.0.0.1:8080)
  SHADOW_PROD_URL                  production origin (https://api.humalike.com)
  SHADOW_PROD_KEY                  production API key (mirroring is off without it)
  SHADOW_MIRROR                    "0" disables mirroring entirely
  SHADOW_SKIP_PATHS                comma-separated path prefixes never mirrored
                                   (default: /internal/)
  SHADOW_PROD_TIMEOUT              seconds per production call (30)
  SHADOW_OUT                       dataset path (tools/shadow/golden/<UTC date>.jsonl)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, Request, WebSocket
from starlette.responses import Response

log = logging.getLogger("shadow")

HOST = os.environ.get("SHADOW_HOST", "127.0.0.1")
PORT = int(os.environ.get("SHADOW_PORT", "8081"))
LOCAL = os.environ.get("SHADOW_LOCAL_URL", "http://127.0.0.1:8080").rstrip("/")
PROD = os.environ.get("SHADOW_PROD_URL", "https://api.humalike.com").rstrip("/")
PROD_KEY = os.environ.get("SHADOW_PROD_KEY", "")
MIRROR = os.environ.get("SHADOW_MIRROR", "1") not in ("0", "false", "no", "")
SKIP_PATHS = tuple(p for p in os.environ.get("SHADOW_SKIP_PATHS", "/internal/").split(",") if p)
PROD_TIMEOUT = float(os.environ.get("SHADOW_PROD_TIMEOUT", "30"))
_default_out = Path(__file__).resolve().parent / "golden" / (
    datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".jsonl")
OUT = Path(os.environ.get("SHADOW_OUT") or _default_out)

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_TOKEN = re.compile(r"(token=)[^&\"'\s]+")
_HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
        "proxy-authorization", "proxy-authenticate", "content-length", "host"}
_KEEP_RESP_HEADERS = ("content-type", "x-request-id", "date", "server", "via",
                      "retry-after", "x-ratelimit-limit", "x-ratelimit-remaining")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def redact(obj: Any) -> Any:
    """Strip grant tokens from anything we persist (connect_url carries one)."""
    if isinstance(obj, str):
        return _TOKEN.sub(r"\1[REDACTED]", obj)
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def parse_body(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return {"_raw": raw.decode("utf-8", "replace")[:4000]}


# ── Dataset writer ─────────────────────────────────────────────────────────────
class Recorder:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._fh = open(self.path, "a", encoding="utf-8")
        self.counts: Dict[str, int] = {"http": 0, "ws_local": 0, "ws_prod": 0, "diverged": 0, "prod_errors": 0}

    async def write(self, rec: Dict[str, Any]) -> None:
        line = json.dumps(redact(rec), ensure_ascii=False, separators=(",", ":"))
        async with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()


recorder: Recorder


# ── Id / epoch remapping for the production mirror ────────────────────────────
class Mapper:
    """local id -> production id, learned by walking paired responses; and
    (local thread, local epoch) -> production epoch from paired submit responses."""

    def __init__(self):
        self.ids: Dict[str, str] = {}
        self.epochs: Dict[str, Dict[int, int]] = {}
        self.prod_thread_of: Dict[str, str] = {}

    def learn(self, local: Any, prod: Any, path: str) -> int:
        before = len(self.ids)
        self._walk(local, prod, path)
        return len(self.ids) - before

    def _walk(self, a: Any, b: Any, path: str) -> None:
        if isinstance(a, dict) and isinstance(b, dict):
            for k, v in a.items():
                if k in b:
                    self._walk(v, b[k], path + "." + k)
        elif isinstance(a, list) and isinstance(b, list):
            for x, y in zip(a, b):
                self._walk(x, y, path + "[]")
        elif isinstance(a, str) and isinstance(b, str) and a != b:
            if _UUID.fullmatch(a) and _UUID.fullmatch(b):
                self.ids[a] = b
                if path.endswith(".thread.id"):
                    self.prod_thread_of[a] = b

    def learn_epoch(self, local_thread: str, local_epoch: Any, prod_epoch: Any) -> None:
        if isinstance(local_epoch, int) and isinstance(prod_epoch, int):
            self.epochs.setdefault(local_thread, {})[local_epoch] = prod_epoch

    def rewrite_text(self, s: str) -> Tuple[str, List[str]]:
        notes: List[str] = []

        def sub(m: re.Match) -> str:
            v = m.group(0)
            if v in self.ids:
                notes.append(f"id {v[:8]}→{self.ids[v][:8]}")
                return self.ids[v]
            return v

        return _UUID.sub(sub, s), notes

    def rewrite_body(self, body: Any, path: str) -> Tuple[Any, List[str]]:
        notes: List[str] = []

        def rw(o: Any) -> Any:
            if isinstance(o, str):
                s, n = self.rewrite_text(o)
                notes.extend(n)
                return s
            if isinstance(o, dict):
                return {k: rw(v) for k, v in o.items()}
            if isinstance(o, list):
                return [rw(v) for v in o]
            return o

        out = rw(body)
        if isinstance(body, dict) and path.endswith("/respond"):
            tid, ep = body.get("thread_id"), body.get("turn_epoch")
            mapped = self.epochs.get(str(tid), {}).get(ep)
            if mapped is not None and mapped != ep:
                out["turn_epoch"] = mapped
                notes.append(f"epoch {ep}→{mapped}")
        return out, notes


mapper = Mapper()


# ── Structural diff (what the report keys on) ─────────────────────────────────
def _status_of(j: Any) -> Optional[str]:
    if isinstance(j, dict):
        for k in ("decision", "status"):
            if isinstance(j.get(k), (str, int)):
                return str(j[k])
        if isinstance(j.get("error"), dict):
            return "error:" + str(j["error"].get("code"))
    return None


def diff(local_status: int, local_body: Any, prod_status: Optional[int], prod_body: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {"status": [local_status, prod_status], "status_equal": local_status == prod_status}
    if isinstance(local_body, dict) and isinstance(prod_body, dict):
        lk, pk = set(local_body), set(prod_body)
        d["keys_local_only"] = sorted(lk - pk)
        d["keys_prod_only"] = sorted(pk - lk)
        for k in ("decision", "turn_epoch", "superseded", "ingested", "tags"):
            if k in local_body or k in prod_body:
                d[k] = [local_body.get(k), prod_body.get(k)]
        if "scheduled" in local_body or "scheduled" in prod_body:
            ls, ps = local_body.get("scheduled") or [], prod_body.get("scheduled") or []
            d["scheduled_count"] = [len(ls), len(ps)]
            d["scheduled_contents"] = [[b.get("content") for b in ls], [b.get("content") for b in ps]]
        if isinstance(local_body.get("error"), dict) or isinstance(prod_body.get("error"), dict):
            d["error_code"] = [(local_body.get("error") or {}).get("code"), (prod_body.get("error") or {}).get("code")]
    flags = []
    if not d["status_equal"]:
        flags.append("status")
    for k in ("decision", "scheduled_count", "error_code", "superseded"):
        v = d.get(k)
        if v and v[0] != v[1]:
            flags.append(k)
    if d.get("keys_local_only") or d.get("keys_prod_only"):
        flags.append("keys")
    d["diverged"] = flags
    return d


# ── Production mirror worker (strictly ordered) ───────────────────────────────
@dataclass
class Pending:
    rec: Dict[str, Any]
    method: str
    path: str
    query: str
    body: Any
    raw: bytes
    content_type: str
    local_status: int
    local_body: Any
    done: asyncio.Event = field(default_factory=asyncio.Event)


queue: "asyncio.Queue[Pending]" = asyncio.Queue()
prod_client: httpx.AsyncClient
local_client: httpx.AsyncClient


async def mirror_worker() -> None:
    while True:
        item = await queue.get()
        try:
            await _mirror_one(item)
        except Exception as e:  # never let the worker die
            log.exception("mirror worker error: %s", e)
            item.rec["prod"] = {"error": f"worker: {e!r}"}
            await recorder.write(item.rec)
        finally:
            item.done.set()
            queue.task_done()


async def _mirror_one(p: Pending) -> None:
    rec = p.rec
    rewrites: List[str] = []
    path, n1 = mapper.rewrite_text(p.path)
    rewrites += n1
    query, n2 = mapper.rewrite_text(p.query)
    rewrites += n2
    content: Optional[bytes]
    if isinstance(p.body, (dict, list)):
        body, n3 = mapper.rewrite_body(p.body, p.path)
        rewrites += n3
        content = json.dumps(body).encode()
    else:
        body, content = None, (p.raw or None)
    headers = {"Authorization": f"Bearer {PROD_KEY}"}
    if p.content_type:
        headers["Content-Type"] = p.content_type
    url = PROD + path + (("?" + query) if query else "")
    t0 = time.perf_counter()
    prod: Dict[str, Any] = {"url_path": path, "request_rewrites": rewrites, "sent_at": now_iso()}
    if body is not None and rewrites:
        prod["request_body"] = body
    try:
        r = await prod_client.request(p.method, url, content=content, headers=headers)
        prod["status"] = r.status_code
        prod["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        prod["headers"] = {k: v for k, v in r.headers.items() if k.lower() in _KEEP_RESP_HEADERS}
        prod["body"] = parse_body(r.content)
        prod["error"] = None
    except Exception as e:
        prod["status"] = None
        prod["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        prod["body"] = None
        prod["error"] = repr(e)
        recorder.counts["prod_errors"] += 1
    rec["prod"] = prod
    # learn mappings from the pair
    learned = 0
    if isinstance(p.local_body, (dict, list)) and isinstance(prod.get("body"), (dict, list)):
        learned = mapper.learn(p.local_body, prod["body"], "")
        if p.path.endswith("/submit_messages") and isinstance(p.body, dict):
            mapper.learn_epoch(str(p.body.get("thread_id")), p.local_body.get("turn_epoch"),
                               prod["body"].get("turn_epoch"))
    prod["ids_learned"] = learned
    rec["diff"] = diff(p.local_status, p.local_body, prod.get("status"), prod.get("body"))
    if rec["diff"]["diverged"]:
        recorder.counts["diverged"] += 1
    rec["completed_at"] = now_iso()
    await recorder.write(rec)
    _console(rec)
    # production realtime: open its grant now (30s TTL) and record frames
    cu = ((prod.get("body") or {}).get("realtime") or {}).get("connect_url") if isinstance(prod.get("body"), dict) else None
    if cu:
        local_tid = ((p.local_body or {}).get("thread") or {}).get("id") if isinstance(p.local_body, dict) else None
        asyncio.create_task(prod_ws_listener(cu, local_tid, rec["seq"]))


def _summ(status: Any, body: Any) -> str:
    s = _status_of(body)
    extra = ""
    if isinstance(body, dict):
        if "turn_epoch" in body:
            extra += f"/e{body['turn_epoch']}"
        if "scheduled" in body:
            extra += f"/{len(body.get('scheduled') or [])}bubbles"
            if body.get("superseded"):
                extra += "/superseded"
    return f"{status} {s or ''}{extra}".strip()


def _console(rec: Dict[str, Any]) -> None:
    l, p = rec["local"], rec.get("prod") or {}
    flags = ",".join((rec.get("diff") or {}).get("diverged") or [])
    log.info("#%d %s %s | local %s %sms | prod %s %sms%s%s",
             rec["seq"], rec["request"]["method"], rec["request"]["path"],
             _summ(l["status"], l["body"]), l["latency_ms"],
             _summ(p.get("status"), p.get("body")) if not p.get("error") else f"ERR {p['error'][:60]}",
             p.get("latency_ms"), f" | rewrites {p['request_rewrites']}" if p.get("request_rewrites") else "",
             f" | DIVERGED({flags})" if flags else "")


# ── WebSocket: bridge client<->local (record) and listen to prod (record) ─────
def _channel_thread(frame: Any) -> Optional[str]:
    ch = frame.get("channel") if isinstance(frame, dict) else None
    if isinstance(ch, str) and "/" in ch:
        return ch.split("/", 1)[1]
    data = frame.get("data") if isinstance(frame, dict) else None
    return data.get("thread_id") if isinstance(data, dict) else None


async def _record_frame(side: str, raw: str, t_open: float, thread: Dict[str, Optional[str]], seq: Optional[int]) -> None:
    try:
        frame = json.loads(raw)
    except Exception:
        frame = {"_raw": raw[:4000]}
    tid = _channel_thread(frame)
    if tid and not thread.get("id"):
        thread["id"] = tid
    recorder.counts["ws_" + side] += 1
    await recorder.write({
        "kind": "ws", "side": side, "ts": now_iso(),
        "recv_offset_ms": round((time.perf_counter() - t_open) * 1000, 1),
        "thread_local": thread.get("local"), "thread_prod": thread.get("prod"), "thread_seen": thread.get("id"),
        "open_seq": seq, "type": frame.get("type") if isinstance(frame, dict) else None, "frame": frame,
    })


async def _ws_event(side: str, event: str, thread: Dict[str, Optional[str]], seq: Optional[int], **detail: Any) -> None:
    await recorder.write({"kind": "ws_event", "side": side, "event": event, "ts": now_iso(),
                          "thread_local": thread.get("local"), "thread_prod": thread.get("prod"),
                          "thread_seen": thread.get("id"), "open_seq": seq, **detail})
    log.info("ws %s %s %s %s", side, event, thread.get("id") or thread.get("local") or "", detail or "")


app = FastAPI(title="humalike shadow proxy")


@app.websocket("/v1/ws/turn-taking-thread")
async def ws_bridge(ws: WebSocket) -> None:
    await ws.accept()
    qs = ws.scope.get("query_string", b"").decode()
    upstream = LOCAL.replace("http", "ws", 1) + "/v1/ws/turn-taking-thread" + (("?" + qs) if qs else "")
    thread: Dict[str, Optional[str]] = {"local": None, "prod": None, "id": None}
    t_open = time.perf_counter()
    close_code, close_reason = 1000, ""
    try:
        async with websockets.connect(upstream, open_timeout=10) as up:
            await _ws_event("local", "open", thread, None)

            async def up_to_client() -> None:
                async for raw in up:
                    text = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
                    await _record_frame("local", text, t_open, thread, None)
                    if not thread["local"] and thread["id"]:
                        thread["local"] = thread["id"]
                        thread["prod"] = mapper.prod_thread_of.get(thread["id"])
                    await ws.send_text(text)

            async def client_to_up() -> None:
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        raise ConnectionError("client disconnected")
                    if msg.get("text") is not None:
                        await up.send(msg["text"])
                    elif msg.get("bytes") is not None:
                        await up.send(msg["bytes"])

            tasks = [asyncio.create_task(up_to_client()), asyncio.create_task(client_to_up())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if isinstance(exc, websockets.ConnectionClosed):
                    close_code = (exc.rcvd.code if exc.rcvd else 1000) or 1000
                    close_reason = (exc.rcvd.reason if exc.rcvd else "") or ""
                elif exc and not isinstance(exc, ConnectionError):
                    raise exc
    except websockets.InvalidStatus as e:  # upstream refused the handshake
        close_code, close_reason = 1011, f"upstream {e.response.status_code}"
    except Exception as e:
        close_code, close_reason = 1011, repr(e)[:100]
    await _ws_event("local", "close", thread, None, code=close_code, reason=close_reason,
                    duration_ms=round((time.perf_counter() - t_open) * 1000, 1))
    try:
        await ws.close(code=close_code, reason=close_reason[:120])
    except Exception:
        pass


async def prod_ws_listener(connect_url: str, local_tid: Optional[str], seq: int) -> None:
    thread: Dict[str, Optional[str]] = {"local": local_tid, "prod": mapper.prod_thread_of.get(local_tid or ""), "id": None}
    t_open = time.perf_counter()
    try:
        async with websockets.connect(connect_url, open_timeout=15) as ws:
            await _ws_event("prod", "open", thread, seq)
            async for raw in ws:
                text = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
                await _record_frame("prod", text, t_open, thread, seq)
        await _ws_event("prod", "close", thread, seq, code=1000, duration_ms=round((time.perf_counter() - t_open) * 1000, 1))
    except websockets.ConnectionClosed as e:
        await _ws_event("prod", "close", thread, seq, code=(e.rcvd.code if e.rcvd else None),
                        reason=(e.rcvd.reason if e.rcvd else ""), duration_ms=round((time.perf_counter() - t_open) * 1000, 1))
    except Exception as e:
        await _ws_event("prod", "error", thread, seq, error=repr(e)[:200])


# ── HTTP: serve from local, queue the mirror ──────────────────────────────────
_seq = 0


def _rewrite_connect_url(body: Any, request: Request) -> Any:
    """Point realtime.connect_url at this proxy so the client's socket is bridged."""
    if not isinstance(body, dict):
        return body
    rt = body.get("realtime")
    if not isinstance(rt, dict) or not isinstance(rt.get("connect_url"), str):
        return body
    parts = urlsplit(rt["connect_url"])
    host = request.headers.get("host") or f"{HOST}:{PORT}"
    scheme = "wss" if request.url.scheme == "https" else "ws"
    rt["connect_url"] = urlunsplit((scheme, host, parts.path, parts.query, parts.fragment))
    return body


# Declared before the catch-all so it is matched first.
@app.get("/internal/shadow/status")
async def status() -> Dict[str, Any]:
    return {"local": LOCAL, "prod": PROD, "mirroring": MIRROR and bool(PROD_KEY), "skip_paths": SKIP_PATHS,
            "dataset": str(OUT), "counts": recorder.counts, "queue_depth": queue.qsize(),
            "id_map_size": len(mapper.ids), "threads_mapped": mapper.prod_thread_of}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy(path: str, request: Request) -> Response:
    global _seq
    _seq += 1
    seq = _seq
    raw = await request.body()
    body = parse_body(raw)
    query = request.url.query
    fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP}
    full = "/" + path
    rec: Dict[str, Any] = {
        "kind": "http", "seq": seq, "ts": now_iso(),
        "request": {"method": request.method, "path": full, "query": query,
                    "headers": {k: v for k, v in request.headers.items()
                                if k.lower() in ("content-type", "user-agent", "idempotency-key", "x-request-id")},
                    "body": body},
    }
    t0 = time.perf_counter()
    try:
        r = await local_client.request(request.method, LOCAL + full + (("?" + query) if query else ""),
                                       content=raw or None, headers=fwd_headers)
    except Exception as e:
        rec["local"] = {"status": 502, "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "error": repr(e), "body": None}
        rec["prod"] = None
        await recorder.write(rec)
        log.error("#%d %s %s | local UNREACHABLE %r", seq, request.method, full, e)
        return Response(json.dumps({"error": {"code": "BAD_GATEWAY", "message": "recreation unreachable"}}),
                        status_code=502, media_type="application/json")
    local_ms = round((time.perf_counter() - t0) * 1000, 1)
    local_body = parse_body(r.content)
    rec["local"] = {"status": r.status_code, "latency_ms": local_ms,
                    "headers": {k: v for k, v in r.headers.items() if k.lower() in _KEEP_RESP_HEADERS},
                    "body": local_body}
    recorder.counts["http"] += 1

    # what the client gets: local's answer, connect_url pointed at the bridge
    out_body = r.content
    if isinstance(local_body, dict) and isinstance(local_body.get("realtime"), dict):
        out_body = json.dumps(_rewrite_connect_url(json.loads(r.content), request)).encode()
    resp_headers = {k: v for k, v in r.headers.items() if k.lower() not in _HOP and k.lower() != "content-length"}
    resp_headers["x-shadow-seq"] = str(seq)

    mirror = MIRROR and bool(PROD_KEY) and not any(full.startswith(s) for s in SKIP_PATHS)
    if mirror:
        await queue.put(Pending(rec, request.method, full, query, body, raw,
                                request.headers.get("content-type", ""), r.status_code, local_body))
    else:
        rec["prod"] = None
        rec["diff"] = None
        await recorder.write(rec)
        log.info("#%d %s %s | local %s %sms | (not mirrored)", seq, request.method, full, _summ(r.status_code, local_body), local_ms)
    return Response(out_body, status_code=r.status_code, headers=resp_headers)


@app.on_event("startup")
async def _startup() -> None:
    global recorder, prod_client, local_client
    recorder = Recorder(OUT)
    local_client = httpx.AsyncClient(timeout=60.0)
    prod_client = httpx.AsyncClient(timeout=PROD_TIMEOUT)
    asyncio.create_task(mirror_worker())
    log.info("shadow proxy on http://%s:%d | local=%s | prod=%s mirroring=%s | dataset=%s | skip=%s",
             HOST, PORT, LOCAL, PROD, MIRROR and bool(PROD_KEY), OUT, SKIP_PATHS)
    if MIRROR and not PROD_KEY:
        log.warning("SHADOW_PROD_KEY is empty — nothing will be mirrored to production")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning", ws="websockets")
