#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_topic.py — 主题驱动的公开情报采集（把外部技术发现注入 TechRadar）。

解决"本地情报库缺少某领域内容"的问题：按关键词从公开源（HN / GitHub）拉取，
经统一管线入库（溯源、去重、FTS 索引），保留原始链接与发布时间。

只访问公开接口，不登录、不绕限流；单次调用数量受控。

用法：
  python collect_topic.py --db <库> --topic "web scraping" --source hn --limit 10
  python collect_topic.py --db <库> --topic "crawler" --source github --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))
sys.path.insert(0, str(ROOT / "06_techradar" / "scripts"))

from skillkit.http import HttpClient  # noqa: E402
from skillkit.inteldb import IntelDB  # noqa: E402
from skillkit.pipeline import Record, ingest  # noqa: E402
from skillkit.policy import CrawlPolicy  # noqa: E402
from skillkit.sources import ensure_registry, set_status, upsert_source  # noqa: E402


def hn_topic(client: HttpClient, topic: str, limit: int) -> list[Record]:
    data = client.get_json("https://hn.algolia.com/api/v1/search",
                           params={"query": topic, "tags": "story", "hitsPerPage": limit})
    out = []
    for hit in data.get("hits", []):
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        out.append(Record(
            url=url, title=hit.get("title") or hit.get("story_title") or "untitled",
            published_at=hit.get("created_at"),
            summary=(hit.get("story_text") or "")[:2000] or None,
            author=hit.get("author"), category="dev",
            tags=["hn", "crawler", topic.lower().replace(" ", "-")],
            metrics={"points": hit.get("points"), "comments": hit.get("num_comments")},
            external_key=f"hn:{hit.get('objectID')}",
            extra={"topic": topic, "hn_id": hit.get("objectID")}))
    return out


def github_topic(client: HttpClient, topic: str, limit: int) -> list[Record]:
    data = client.get_json("https://api.github.com/search/repositories",
                           params={"q": f"{topic} stars:>200", "sort": "stars",
                                   "order": "desc", "per_page": limit})
    out = []
    for item in data.get("items", []):
        lic = (item.get("license") or {}).get("spdx_id")
        out.append(Record(
            url=item["html_url"], title=item["full_name"],
            published_at=item.get("created_at"),
            summary=(item.get("description") or "")[:1000] or None,
            author=(item.get("owner") or {}).get("login"), category="opensource",
            tags=["github", "crawler", (lic or "unknown-license").lower()],
            metrics={"stars": item.get("stargazers_count"), "forks": item.get("forks_count"),
                     "open_issues": item.get("open_issues_count"), "license": lic},
            external_key=f"gh:{item['full_name']}",
            extra={"topic": topic, "pushed_at": item.get("pushed_at"),
                   "language": item.get("language"), "archived": item.get("archived")}))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "06_techradar" / "data" / "techradar.db"))
    ap.add_argument("--topic", required=True)
    ap.add_argument("--source", choices=["hn", "github", "both"], default="both")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    policy = CrawlPolicy(timeout_seconds=25, max_retries=2, min_interval_seconds=2.0)
    client = HttpClient(policy)
    collected: list[Record] = []
    errors = []
    if args.source in ("hn", "both"):
        try:
            collected += hn_topic(client, args.topic, args.limit)
        except Exception as exc:
            errors.append(f"hn: {type(exc).__name__}: {exc}")
    if args.source in ("github", "both"):
        try:
            collected += github_topic(client, args.topic, args.limit)
        except Exception as exc:
            errors.append(f"github: {type(exc).__name__}: {exc}")

    with IntelDB(args.db) as db:
        ensure_registry(db.conn)
        upsert_source(db.conn, "topic_search", "主题检索（HN/GitHub）", "api", "public",
                      notes="按关键词动态检索公开源，用于补齐情报缺口")
        stats = ingest(db, collected, "topic_search", "api")
        set_status(db.conn, "topic_search", "READY", fetched=stats["inserted"] + stats["deduped"],
                   inserted=stats["inserted"], deduped=stats["deduped"], succeeded=True,
                   connectivity_status="ONLINE", collection_status="SUCCESS",
                   configuration_status="CONFIGURED", last_error="")
        total = db.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    result = {"topic": args.topic, "source": args.source, "fetched": len(collected),
              "inserted": stats["inserted"], "deduped": stats["deduped"],
              "quarantined": stats["quarantined"], "errors": errors,
              "db_entries": total}
    print(f"topic={args.topic} fetched={len(collected)} inserted={stats['inserted']} "
          f"dedup={stats['deduped']} quarantined={stats['quarantined']} db={total}")
    for e in errors:
        print("  WARN", e)
    if args.report:
        p = Path(args.report)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"-> {p}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
