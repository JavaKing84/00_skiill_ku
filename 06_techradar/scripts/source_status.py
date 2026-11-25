#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""source_status.py — 数据源注册表巡检与状态清单。

输出每个来源的：状态、授权状态、凭据状态、连通状态、上次尝试/成功时间、错误、累计采集/入库数。
同时输出双通道汇总，并给出"哪些通道可用、哪些需要人工"的明确结论。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))

from skillkit.inteldb import IntelDB  # noqa: E402
from skillkit.sources import STATUS_DOC as STATUS_MEANING, ensure_registry, list_sources, summary  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "06_techradar" / "data" / "techradar.db"))
    ap.add_argument("--json", default="", help="输出 JSON 报告路径")
    args = ap.parse_args()

    with IntelDB(args.db) as db:
        ensure_registry(db.conn)
        rows = list_sources(db.conn)
        summ = summary(db.conn)
        total_entries = db.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        try:
            fts_rows = db.conn.execute("SELECT COUNT(*) FROM entries_fts").fetchone()[0]
        except sqlite3_error():  # noqa: F821
            fts_rows = None

    print(f"{'source_id':22s} {'channel':14s} {'status':18s} {'impl':12s} {'config':13s} "
          f"{'auth':12s} {'cred':10s} {'conn':10s} {'collect':10s} {'ok':>6s} {'last_ok':20s}")
    for r in rows:
        print(f"{r['source_id']:22s} {r['channel']:14s} {r['status']:18s} "
              f"{r.get('implementation_status') or '-':12s} "
              f"{r.get('configuration_status') or '-':13s} "
              f"{r['authorization_status']:12s} {r['credential_status']:10s} "
              f"{r['connectivity_status']:10s} {r.get('collection_status') or '-':10s} "
              f"{r['items_inserted']:6d} {(r['last_success_at'] or '-')[:19]:20s}")
        if r["last_error"]:
            print(f"    last_error: {r['last_error'][:110]}")

    by_channel: dict[str, dict] = {}
    for r in rows:
        ch = by_channel.setdefault(r["channel"], {"sources": 0, "ready": 0, "inserted": 0})
        ch["sources"] += 1
        ch["ready"] += 1 if r["status"] == "READY" else 0
        ch["inserted"] += r["items_inserted"]

    print("\n状态含义：")
    for k, v in STATUS_MEANING.items():
        print(f"  {k:20s} {v}")
    print(f"\n汇总：来源 {summ['total']} 个 {summ['by_status']}；累计采集 {summ['fetched']}，"
          f"入库 {summ['inserted']}，去重 {summ['deduped']}")
    print(f"库内条目 {total_entries}，FTS 索引 {fts_rows} 行")
    for ch, v in sorted(by_channel.items()):
        print(f"  通道 {ch:16s} 来源 {v['sources']}，就绪 {v['ready']}，入库 {v['inserted']}")

    payload = {"sources": rows, "summary": summ, "by_channel": by_channel,
               "db_entries": total_entries, "fts_rows": fts_rows,
               "status_meaning": STATUS_MEANING}
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"-> {p}")
    return 0


def sqlite3_error():
    import sqlite3
    return sqlite3.Error


if __name__ == "__main__":
    raise SystemExit(main())
