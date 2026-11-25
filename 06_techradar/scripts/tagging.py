#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tagging.py — 特征标签自动打标（排障型情报）。

标签体系（与 radar_query --tag 对应）：
  anti-bot            403/401/429、cloudflare、captcha、stealth、headless、反爬、风控
  troubleshooting     报错、异常、timeout、failed、0x80070005、无法/失败
  windows-permission  schtasks、SYSTEM、S4U、管理员、Access is denied、权限
  code-snippet        正文/摘要含 <pre><code> 或 ``` 代码块
  playwright / curl-cffi / reddit  技术栈标签

用法：
  python tagging.py --db ...\techradar.db --hours 6     # 给最近入库条目标签
  python tagging.py --db ...\techradar.db --all         # 全量补标（幂等）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))

from skillkit.inteldb import IntelDB  # noqa: E402

RULES: list[tuple[str, re.Pattern]] = [
    ("anti-bot", re.compile(
        r"403|401|429|bypass|cloudflare|captcha|anti[-_ ]?bot|bot detection|"
        r"stealth|headless|impersonate|tls fingerprint|反爬|风控|封禁|拦截", re.I)),
    ("troubleshooting", re.compile(
        r"error|exception|traceback|failed|failure|timeout|timed out|"
        r"0x[0-9a-f]{8}|crash|hang|报错|错误|失败|异常|无法|卡住|排查", re.I)),
    ("windows-permission", re.compile(
        r"schtasks|scheduled task|计划任务|system account|s4u|runlevel|"
        r"access is denied|0x80070005|管理员|权限|提权|elevat", re.I)),
    ("playwright", re.compile(r"playwright", re.I)),
    ("curl-cffi", re.compile(r"curl[_-]?cffi|impersonate", re.I)),
    ("reddit", re.compile(r"reddit|shreddit", re.I)),
]

CODE_PATTERNS = (
    re.compile(r"<pre[^>]*>\s*<code", re.I),
    re.compile(r"```"),
)


def has_code(text: str) -> bool:
    return bool(text) and any(p.search(text) for p in CODE_PATTERNS)


def classify(title: str, summary: str = "", content: str = "") -> list[str]:
    blob = " ".join(x for x in (title, summary, content) if x)
    tags = [name for name, rx in RULES if rx.search(blob)]
    if has_code(blob):
        tags.append("code-snippet")
    return tags


def tag_recent(db_path: str, hours: float | None = 6, batch: int = 3000) -> dict:
    since = None
    if hours is not None:
        since = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
    stats = {"scanned": 0, "tagged": 0, "tags_added": 0}
    with IntelDB(Path(db_path)) as db:
        sql = ("SELECT entry_id, title, summary, extra_json, collected_at FROM entries "
               "WHERE 1=1")
        args: list = []
        if since:
            sql += " AND collected_at >= ?"
            args.append(since)
        sql += " ORDER BY entry_id DESC LIMIT ?"
        args.append(batch)
        for row in db.conn.execute(sql, args).fetchall():
            stats["scanned"] += 1
            extra = {}
            try:
                extra = json.loads(row["extra_json"] or "{}")
            except json.JSONDecodeError:
                extra = {}
            content = str(extra.get("content") or "")
            if extra.get("code_snippets"):
                content += "\n```\n"
            tags = classify(row["title"] or "", row["summary"] or "", content)
            if not tags:
                continue
            before = {r[0] for r in db.conn.execute(
                "SELECT t.name FROM entry_tags et JOIN tags t ON t.tag_id=et.tag_id "
                "WHERE et.entry_id=?", (row["entry_id"],))}
            new = [t for t in tags if t not in before]
            if new:
                db.add_tags(int(row["entry_id"]), new)
                stats["tagged"] += 1
                stats["tags_added"] += len(new)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--hours", type=float, default=6, help="最近 N 小时入库的条目；0 表示全量")
    ap.add_argument("--all", action="store_true", help="全量补标")
    ap.add_argument("--batch", type=int, default=3000)
    args = ap.parse_args()
    hours = None if args.all or args.hours == 0 else args.hours
    stats = tag_recent(args.db, hours=hours, batch=args.batch)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
