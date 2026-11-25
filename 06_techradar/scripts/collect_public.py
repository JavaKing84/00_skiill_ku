#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_public.py — 公开情报源采集（TechRadar 降级链，Phase 3.2/3.5）。

数据源（均无需登录、公开 API、低频单次）：
  hn     Hacker News Algolia API（front_page）
  github GitHub Search API（按 star 降序，未认证限额 10 次/分钟，本脚本每次最多 1 次请求）
注意：这些是公开替代源，不等同于用户的 Folo/Reddit 订阅，报告会显式标注。
重复运行同一查询即验证 entries.content_hash 去重。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
from skillkit.inteldb import IntelDB  # noqa: E402
from skillkit.policy import CrawlPolicy  # noqa: E402

UA = {"User-Agent": "skillkit-techradar/1.0 (+local research; low frequency)"}


def collect_hn(limit: int) -> list[dict]:
    url = f"https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage={limit}"
    r = requests.get(url, headers=UA, timeout=CrawlPolicy().timeout_seconds)
    r.raise_for_status()
    rows = []
    for hit in r.json().get("hits", []):
        rows.append({
            "source": ("Hacker News (public fallback)", "hn"),
            "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
            "title": hit.get("title"),
            "author": hit.get("author"),
            "published_at": hit.get("created_at"),
            "summary": (hit.get("story_text") or "")[:500],
            "metrics": {"points": hit.get("points"), "comments": hit.get("num_comments")},
        })
    return rows


def collect_github(query: str, limit: int) -> list[dict]:
    url = "https://api.github.com/search/repositories"
    r = requests.get(url, headers=UA, params={"q": query, "sort": "stars",
                                              "order": "desc", "per_page": limit},
                     timeout=CrawlPolicy().timeout_seconds)
    r.raise_for_status()
    rows = []
    for item in r.json().get("items", []):
        rows.append({
            "source": ("GitHub Search (public fallback)", "github"),
            "url": item["html_url"],
            "title": item["full_name"],
            "author": (item.get("owner") or {}).get("login"),
            "published_at": item.get("created_at"),
            "summary": (item.get("description") or "")[:500],
            "metrics": {"stars": item.get("stargazers_count"),
                        "forks": item.get("forks_count"),
                        "license": (item.get("license") or {}).get("spdx_id")},
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--source", choices=["hn", "github", "both"], default="both")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--query", default="created:>2025-01-01 stars:>1000",
                    help="GitHub 搜索查询（仅 source=github/both 时使用）")
    args = ap.parse_args()

    batches: list[dict] = []
    if args.source in ("hn", "both"):
        batches += collect_hn(args.limit)
    if args.source in ("github", "both"):
        batches += collect_github(args.query, args.limit)

    inserted = duplicated = 0
    with IntelDB(args.db) as db:
        for row in batches:
            (sname, skind) = row.pop("source")
            verdict = db.add_entry(source_name=sname, source_kind=skind, url=row["url"],
                                   title=row["title"], author=row["author"],
                                   published_at=row["published_at"], summary=row["summary"],
                                   metrics=row["metrics"])
            inserted += verdict == "inserted"
            duplicated += verdict == "duplicate"
        stats = db.stats()
    print(f"fetched={len(batches)} inserted={inserted} duplicate={duplicated} db_stats={stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
