#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_github_issues.py — 排障型情报源：GitHub Issues 搜索。

零凭证可用（GitHub 公共 Search API，未认证 10 次/分钟）；可选 GITHUB_TOKEN 提高配额。
按「报错/反爬」类查询抓 Issue，保留标题、正文、代码块，写入 tag: github-issues。

用法：
  python collect_github_issues.py --db ...\\techradar.db --limit 8
  python collect_github_issues.py --queries "playwright 403 bypass,schtasks 0x80070005"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from skillkit.http import HttpClient, load_dotenv  # noqa: E402
from skillkit.inteldb import IntelDB  # noqa: E402
from skillkit.pipeline import Record, SourceSpec, run_source  # noqa: E402
from skillkit.policy import CrawlPolicy  # noqa: E402
import snippets  # noqa: E402
import tagging  # noqa: E402

API = "https://api.github.com/search/issues"
DEFAULT_QUERIES = [
    "playwright 403 bypass",
    "curl_cffi impersonate",
    "schtasks 0x80070005",
    "headless chrome detection",
]


def fetch(client: HttpClient, queries: list[str], limit: int) -> list[Record]:
    recs: list[Record] = []
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for q in queries:
        url = f"{API}?q={urllib.parse.quote(q)}&sort=updated&order=desc&per_page={min(limit, 30)}"
        try:
            r = client.get(url, headers=headers, timeout=25)
            data = r.json()
        except Exception:
            time.sleep(7)
            continue
        for it in (data.get("items") or [])[:limit]:
            title = (it.get("title") or "").strip()
            html_url = it.get("html_url") or ""
            if not title or not html_url:
                continue
            body = it.get("body") or ""
            codes = snippets.extract_md(body)
            content = body[:20000]
            recs.append(Record(
                url=html_url, title=title,
                published_at=it.get("created_at"),
                summary=(body[:1800] or None),
                content=content or None,
                author=((it.get("user") or {}).get("login")),
                category="troubleshooting",
                tags=["github-issues"] + tagging.classify(title, body[:2000], content),
                external_key=f"github-issue:{it.get('id') or html_url}",
                extra={"origin_source": "github", "query": q,
                       "repo": (it.get("repository_url") or "").rsplit("/", 2)[-2:],
                       "state": it.get("state"), "comments": it.get("comments"),
                       "code_snippets": codes[:10]},
            ))
        time.sleep(7)          # 未认证 10 次/分钟
    return recs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "06_techradar" / "data" / "techradar.db"))
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--queries", default=",".join(DEFAULT_QUERIES))
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    policy = CrawlPolicy(timeout_seconds=25, max_retries=2, min_interval_seconds=2.0)
    client = HttpClient(policy)
    with IntelDB(Path(args.db)) as db:
        spec = SourceSpec(
            source_id="github_issues", source_name="GitHub Issues（排障搜索）",
            source_type="api", channel="public",
            fetch=lambda: fetch(client, queries, args.limit),
            aggregator=None, origin_extra_key="origin_source")
        result = run_source(db, db.conn, spec)
        total = db.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    print(f"github_issues status={result['status']} fetched={result['fetched']} "
          f"inserted={result['inserted']} dedup={result['deduped']} error={result['error']}")
    print(f"库内条目 {total}")
    if args.report:
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
