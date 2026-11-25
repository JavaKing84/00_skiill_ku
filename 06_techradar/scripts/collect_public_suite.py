#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_public_suite.py — 通道 A 编排器：零凭证公开情报采集。

流程：发现 → 采集 → 解析 → 清洗 → 去重 → 入库 → FTS5 索引（复用统一管线）。
故障隔离：任一来源失败只影响该来源；单个博客/仓库失败不影响同组其它来源；
调度器不会因某个来源异常而退出。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))

from skillkit.http import HttpClient  # noqa: E402
from skillkit.inteldb import IntelDB  # noqa: E402
from skillkit.pipeline import run_sources  # noqa: E402
from skillkit.policy import CrawlPolicy  # noqa: E402
from skillkit.sources import ensure_registry, list_sources, summary  # noqa: E402

sys.path.insert(0, str(ROOT / "06_techradar" / "scripts"))
from public_sources import build_specs  # noqa: E402

DB_DEFAULT = ROOT / "06_techradar" / "data" / "techradar.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_DEFAULT))
    ap.add_argument("--limit", type=int, default=20, help="每个来源最多取多少条")
    ap.add_argument("--only", default="", help="逗号分隔的 source_id 白名单")
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"FAIL: 情报库不存在 {db_path}")
        return 2

    policy = CrawlPolicy(timeout_seconds=25, max_retries=3, backoff_base_seconds=2.0,
                         min_interval_seconds=1.0)
    client = HttpClient(policy)
    specs = build_specs(client, limit=args.limit)
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        specs = [s for s in specs if s.source_id in wanted]

    started = datetime.now().isoformat(timespec="seconds")
    with IntelDB(db_path) as db:
        ensure_registry(db.conn)
        results = run_sources(db, db.conn, specs)
        reg = list_sources(db.conn)
        stats = summary(db.conn)
        total_entries = db.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        fts_rows = db.conn.execute("SELECT COUNT(*) FROM entries_fts").fetchone()[0]

    print(f"{'source_id':22s} {'status':12s} {'fetched':>7s} {'inserted':>8s} {'dedup':>6s}  error")
    for r in results:
        print(f"{r['source_id']:22s} {r['status']:12s} {r['fetched']:7d} {r['inserted']:8d} "
              f"{r['deduped']:6d}  {(r['error'] or '')[:70]}")

    ready = [r for r in results if r["status"] == "READY"]
    report = {
        "channel": "public",
        "ran_at": started,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "requests": client.request_count,
        "sources_total": len(results),
        "sources_ready": len(ready),
        "sources_failed": len(results) - len(ready),
        "inserted": sum(r["inserted"] for r in results),
        "deduped": sum(r["deduped"] for r in results),
        "results": results,
        "registry": reg,
        "registry_summary": stats,
        "db_entries": total_entries,
        "fts_rows": fts_rows,
        "credentials_used": "NONE（通道 A 零凭证）",
    }
    print(f"\n来源 {len(ready)}/{len(results)} 就绪；新入库 {report['inserted']}，去重 {report['deduped']}；"
          f"库内条目 {total_entries}，FTS 索引 {fts_rows} 行")
    # 机器可读汇总（供 lifecycle_run 统计 job_runs，避免解析中文描述）
    print(f"SUMMARY collected={sum(r['fetched'] for r in results)} inserted={report['inserted']} "
          f"deduped={report['deduped']} failed={report['sources_failed']}")
    if args.report:
        p = Path(args.report)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"-> {p}")
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
