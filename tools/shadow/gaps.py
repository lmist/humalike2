#!/usr/bin/env python3
"""Parity-gap digest from the shadow golden dataset (SQLite).

Turns the raw pairs into the handful of questions a fix plan needs answered:
where does our router disagree with production, how does production split and
pace bubbles versus us, does its naturalizer rewrite text, which response keys
differ per endpoint, and how far apart are latencies. Every finding cites the
exchange ``seq`` so a bead can point at evidence.

    tools/shadow/gaps.py [--db golden/shadow.sqlite] [--json]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def j(s):
    try:
        return json.loads(s) if s else None
    except Exception:
        return None


def ts_ms(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).timestamp() * 1000
    except Exception:
        return None


def key_paths(o, prefix=""):
    out = set()
    if isinstance(o, dict):
        for k, v in o.items():
            p = f"{prefix}.{k}" if prefix else k
            out.add(p)
            out |= key_paths(v, p)
    elif isinstance(o, list) and o:
        out |= key_paths(o[0], prefix + "[]")
    return out


def words(s):
    return len((s or "").split())


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=HERE / "golden" / "shadow.sqlite")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv[1:])
    db = sqlite3.connect(str(a.db))
    db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute("select * from exchanges where mirrored=1 and prod_status is not null order by seq")]
    valid = [r for r in rows if r["prod_status"] == 200 and r["local_status"] == 200]
    report = {"db": str(a.db), "pairs": len(rows), "pairs_200_both": len(valid)}

    # ── 1. Router decisions ───────────────────────────────────────────────────
    dec = [r for r in valid if r["path"].endswith("/submit_messages")]
    agree = [r for r in dec if r["decision_local"] == r["decision_prod"]]
    dis = [r for r in dec if r["decision_local"] != r["decision_prod"]]
    conf = Counter((r["decision_local"], r["decision_prod"]) for r in dec)
    report["router"] = {
        "pairs": len(dec), "agree": len(agree), "disagree": len(dis),
        "confusion(ours,theirs)": {f"{k[0]}/{k[1]}": v for k, v in conf.items()},
        "disagreements": [],
    }
    for r in dis:
        body = j(r["request_body"]) or {}
        msgs = body.get("messages") or []
        last = msgs[-1] if msgs else {}
        lb, pb = j(r["local_body"]) or {}, j(r["prod_body"]) or {}
        report["router"]["disagreements"].append({
            "seq": r["seq"], "thread": (r["thread_local"] or "")[:8], "epoch": r["epoch_local"],
            "batch": len(msgs), "sender": last.get("sender"), "last": (last.get("content") or "")[:80],
            "words": words(last.get("content")), "has_media": bool(last.get("has_media")),
            "ours": r["decision_local"], "theirs": r["decision_prod"],
            "tags": [lb.get("tags"), pb.get("tags")],
            "recalled": [len(lb.get("recalled_context") or ""), len(pb.get("recalled_context") or "")],
            "system_prompt_words": words(body.get("system_prompt")),
        })
    # short/low-content heuristic: how often does prod stay silent on <=3-word messages?
    short = [r for r in dec if words(((j(r["request_body"]) or {}).get("messages") or [{}])[-1].get("content")) <= 3]
    report["router"]["short_messages(<=3 words)"] = {
        "n": len(short),
        "theirs_silent": sum(1 for r in short if r["decision_prod"] == "stay_silent"),
        "ours_silent": sum(1 for r in short if r["decision_local"] == "stay_silent"),
    }
    # recalled_context / tags presence
    report["router"]["recalled_context_nonempty"] = {
        "ours": sum(1 for r in dec if (j(r["local_body"]) or {}).get("recalled_context")),
        "theirs": sum(1 for r in dec if (j(r["prod_body"]) or {}).get("recalled_context")),
    }

    # ── 2. Naturalizer: split + rewrite ───────────────────────────────────────
    resp = [r for r in valid if r["path"].endswith("/respond")]
    nat = {"pairs": len(resp), "count_equal": 0, "text_preserved_ours": 0, "text_preserved_theirs": 0,
           "superseded": [], "cases": []}
    for r in resp:
        body = j(r["request_body"]) or {}
        draft = body.get("content") or ""
        lb, pb = j(r["local_body"]) or {}, j(r["prod_body"]) or {}
        ls, ps = lb.get("scheduled") or [], pb.get("scheduled") or []
        if lb.get("superseded") or pb.get("superseded"):
            nat["superseded"].append({"seq": r["seq"], "ours": lb.get("superseded"), "theirs": pb.get("superseded")})
        lc, pc = [b.get("content") or "" for b in ls], [b.get("content") or "" for b in ps]
        norm = lambda s: " ".join(s.split())
        l_pres = norm(" ".join(lc)) == norm(draft)
        p_pres = norm(" ".join(pc)) == norm(draft)
        nat["count_equal"] += int(len(ls) == len(ps))
        nat["text_preserved_ours"] += int(l_pres)
        nat["text_preserved_theirs"] += int(p_pres)
        # pacing from deliver_at vs created_at
        def offsets(sched):
            if not sched:
                return []
            c0 = ts_ms(sched[0].get("created_at"))
            return [round((ts_ms(b.get("deliver_at")) - c0) / 1000, 1) if c0 and ts_ms(b.get("deliver_at")) else None for b in sched]
        lo, po = offsets(ls), offsets(ps)
        nat["cases"].append({
            "seq": r["seq"], "draft_words": words(draft), "draft_paras": len([p for p in draft.split("\n\n") if p.strip()]),
            "bubbles": [len(ls), len(ps)], "words_per_bubble": [[words(c) for c in lc], [words(c) for c in pc]],
            "deliver_offsets_s": [lo, po], "text_preserved": [l_pres, p_pres],
            "pacing_req": body.get("pacing"), "draft": draft[:120],
            "ours": [c[:90] for c in lc], "theirs": [c[:90] for c in pc],
        })
    report["naturalizer"] = nat

    # ── 3. Realtime frames: typing lead, bubble timing per side ──────────────
    frames = [dict(r) for r in db.execute("select * from ws_frames order by thread_seen, side, recv_offset_ms")]
    per = defaultdict(lambda: defaultdict(list))
    for f in frames:
        per[f["thread_seen"] or "?"][f["side"]].append(f)
    rt = {"threads": []}
    typing_leads = {"local": [], "prod": []}
    for tid, sides in per.items():
        entry = {"thread": (tid or "?")[:8]}
        for side in ("local", "prod"):
            fs = sides.get(side, [])
            msgs = [f for f in fs if f["type"] == "turn_taking.message"]
            typ = [f for f in fs if f["type"] == "turn_taking.typing"]
            # typing lead = first message after a typing=true minus that typing frame
            leads = []
            for t in typ:
                if t["typing"]:
                    nxt = next((m for m in msgs if m["recv_offset_ms"] > t["recv_offset_ms"]), None)
                    if nxt:
                        leads.append(round((nxt["recv_offset_ms"] - t["recv_offset_ms"]) / 1000, 1))
            typing_leads[side] += leads
            gaps = [round((b["recv_offset_ms"] - a["recv_offset_ms"]) / 1000, 1) for a, b in zip(msgs, msgs[1:])]
            entry[side] = {"frames": len(fs), "messages": len(msgs), "typing_leads_s": leads, "gaps_s": gaps,
                           "types": sorted(set(f["type"] for f in fs if f["type"]))}
        rt["threads"].append(entry)
    rt["typing_lead_s_median"] = {k: (statistics.median(v) if v else None) for k, v in typing_leads.items()}
    rt["typing_lead_s_all"] = typing_leads
    # frame shape differences
    shape = {}
    for side in ("local", "prod"):
        ks = set()
        for f in frames:
            if f["side"] == side:
                ks |= key_paths(j(f["frame"]))
        shape[side] = sorted(ks)
    rt["frame_keys_local_only"] = sorted(set(shape["local"]) - set(shape["prod"]))
    rt["frame_keys_prod_only"] = sorted(set(shape["prod"]) - set(shape["local"]))
    ev = [dict(r) for r in db.execute("select side, event, code, reason, count(*) n from ws_events group by side, event, code, reason")]
    rt["ws_events"] = ev
    report["realtime"] = rt

    # ── 4. Response-shape differences per endpoint ───────────────────────────
    shapes = {}
    for path in sorted(set(r["path"] for r in valid)):
        lk, pk = set(), set()
        for r in valid:
            if r["path"] == path:
                lk |= key_paths(j(r["local_body"]))
                pk |= key_paths(j(r["prod_body"]))
        shapes[path] = {"n": sum(1 for r in valid if r["path"] == path),
                        "local_only": sorted(lk - pk), "prod_only": sorted(pk - lk)}
    report["response_shapes"] = shapes

    # ── 5. Status / error divergences (non-200 on either side) ───────────────
    report["status_divergence"] = [
        {"seq": r["seq"], "path": r["path"], "ours": r["local_status"], "theirs": r["prod_status"],
         "theirs_error": ((j(r["prod_body"]) or {}).get("error") or {}).get("code") if isinstance(j(r["prod_body"]), dict) else None}
        for r in rows if r["local_status"] != r["prod_status"]]

    # ── 6. Latency ───────────────────────────────────────────────────────────
    lat = {}
    for path in sorted(set(r["path"] for r in valid)):
        ls = [r["local_latency_ms"] for r in valid if r["path"] == path and r["local_latency_ms"] is not None]
        ps = [r["prod_latency_ms"] for r in valid if r["path"] == path and r["prod_latency_ms"] is not None]
        lat[path] = {"n": len(ls), "ours_median_ms": round(statistics.median(ls)) if ls else None,
                     "theirs_median_ms": round(statistics.median(ps)) if ps else None}
    report["latency"] = lat

    # ── 7. Social-learning extract: profile diffs ────────────────────────────
    sl = [r for r in valid if r["path"].endswith("/social-learning/actions/extract")]
    if sl:
        out = []
        for r in sl:
            lb, pb = j(r["local_body"]) or {}, j(r["prod_body"]) or {}
            out.append({"seq": r["seq"], "keys": [sorted(lb) if isinstance(lb, dict) else None, sorted(pb) if isinstance(pb, dict) else None],
                        "prompt_block_words": [words(json.dumps(lb.get("prompt_block")) if lb.get("prompt_block") else ""),
                                               words(json.dumps(pb.get("prompt_block")) if pb.get("prompt_block") else "")],
                        "profiles_keys": [sorted((lb.get("profiles") or [{}])[0]) if isinstance(lb.get("profiles"), list) and lb.get("profiles") else None,
                                          sorted((pb.get("profiles") or [{}])[0]) if isinstance(pb.get("profiles"), list) and pb.get("profiles") else None]})
        report["social_learning"] = out

    if a.json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
        return 0

    # ── text digest ──────────────────────────────────────────────────────────
    R = report
    print(f"pairs: {R['pairs']} (both 200: {R['pairs_200_both']})\n")
    rt_ = R["router"]
    print(f"ROUTER  agree {rt_['agree']}/{rt_['pairs']}  confusion {rt_['confusion(ours,theirs)']}")
    print(f"        short msgs: {rt_['short_messages(<=3 words)']}   recalled_context nonempty: {rt_['recalled_context_nonempty']}")
    for d in rt_["disagreements"]:
        print(f"  #{d['seq']:<3} e{d['epoch']} batch={d['batch']} {d['sender']}: {d['last']!r} ({d['words']}w) ours={d['ours']} theirs={d['theirs']} tags={d['tags']}")
    n = R["naturalizer"]
    print(f"\nNATURALIZER  pairs {n['pairs']}  count_equal {n['count_equal']}  text_preserved ours {n['text_preserved_ours']} theirs {n['text_preserved_theirs']}  superseded {n['superseded']}")
    for c in n["cases"]:
        print(f"  #{c['seq']:<3} draft {c['draft_words']}w/{c['draft_paras']}p -> bubbles {c['bubbles']} words {c['words_per_bubble']} offsets_s {c['deliver_offsets_s']} preserved {c['text_preserved']} pacing_req {c['pacing_req']}")
        if not c["text_preserved"][1]:
            for i, t in enumerate(c["theirs"]):
                print(f"        theirs[{i}] {t!r}")
            for i, t in enumerate(c["ours"]):
                print(f"        ours[{i}]   {t!r}")
    r_ = R["realtime"]
    print(f"\nREALTIME  typing lead median s {r_['typing_lead_s_median']}  frame keys local-only {r_['frame_keys_local_only']} prod-only {r_['frame_keys_prod_only']}")
    for t in r_["threads"]:
        print(f"  {t['thread']}: local {t.get('local', {}).get('messages')} msgs leads {t.get('local', {}).get('typing_leads_s')} gaps {t.get('local', {}).get('gaps_s')} | prod {t.get('prod', {}).get('messages')} msgs leads {t.get('prod', {}).get('typing_leads_s')} gaps {t.get('prod', {}).get('gaps_s')}")
    print(f"  ws events: {r_['ws_events']}")
    print("\nRESPONSE SHAPES (keys present on one side only)")
    for p, s in R["response_shapes"].items():
        if s["local_only"] or s["prod_only"]:
            print(f"  {p} (n={s['n']}): local-only {s['local_only']} | prod-only {s['prod_only']}")
    print(f"\nSTATUS DIVERGENCE: {R['status_divergence']}")
    print("\nLATENCY median ms (ours / theirs)")
    for p, l in R["latency"].items():
        print(f"  {p:55} {l['ours_median_ms']:>6} / {l['theirs_median_ms']:>6}  (n={l['n']})")
    if "social_learning" in R:
        print("\nSOCIAL LEARNING extract")
        for s in R["social_learning"]:
            print(f"  #{s['seq']} keys {s['keys']} prompt_block words {s['prompt_block_words']} profile keys {s['profiles_keys']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
