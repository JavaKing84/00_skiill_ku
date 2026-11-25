#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_reddit_topics.py — 排障型情报源：Reddit 技术板块讨论。

复用 websession 的真实浏览器登录态（offscreen 窗口 + DOM 抓取），
默认板块：r/webscraping、r/Python。写入 source_id=reddit_tech。

用法：
  python collect_reddit_topics.py --db ...\\techradar.db --subreddits webscraping,Python --limit 15
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from skillkit.inteldb import IntelDB  # noqa: E402
from skillkit.pipeline import Record, SourceSpec, run_source  # noqa: E402
import tagging  # noqa: E402
from websession import reddit_fetch  # noqa: E402


def _enrich(recs: list[Record]) -> list[Record]:
    for r in recs:
        extra_tags = tagging.classify(r.title, r.summary or "")
        for t in extra_tags:
            if t not in r.tags:
                r.tags.append(t)
    return recs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "06_techradar" / "data" / "techradar.db"))
    ap.add_argument("--subreddits", default="webscraping,Python")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    subs = [s.strip() for s in args.subreddits.split(",") if s.strip()]
    with IntelDB(Path(args.db)) as db:
        spec = SourceSpec(
            source_id="reddit_tech", source_name="Reddit 技术板块（排障）",
            source_type="api", channel="browser",
            fetch=lambda: _enrich(reddit_fetch(subs, limit=args.limit)),
            auth_required=True, authorization_status="granted", credential_status="valid",
            aggregator="reddit", origin_extra_key="origin_source")
        result = run_source(db, db.conn, spec)
        total = db.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    print(f"reddit_tech status={result['status']} fetched={result['fetched']} "
          f"inserted={result['inserted']} dedup={result['deduped']} error={result['error']}")
    print(f"库内条目 {total}")
    if args.report:
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
