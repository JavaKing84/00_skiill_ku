#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_stackoverflow.py — 排障型情报源：Stack Overflow 指定 Tag。

StackExchange 公共 API（无需 key，配额 300/天）：
  https://api.stackexchange.com/2.3/questions?site=stackoverflow&tagged=<tag>
保留问题正文与 <pre><code> 代码块，写入 tag: stackoverflow。

用法：
  python collect_stackoverflow.py --db ...\\techradar.db --tags playwright,python-requests --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from skillkit.http import HttpClient  # noqa: E402
from skillkit.inteldb import IntelDB  # noqa: E402
from skillkit.pipeline import Record, SourceSpec, run_source  # noqa: E402
from skillkit.policy import CrawlPolicy  # noqa: E402
import snippets  # noqa: E402
import tagging  # noqa: E402

API = "https://api.stackexchange.com/2.3/questions"
DEFAULT_TAGS = ["playwright", "python-requests"]


def _strip_html(raw: str) -> str:
    import re
    s = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", raw or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fetch(client: HttpClient, tags: list[str], limit: int) -> list[Record]:
    recs: list[Record] = []
    for tag in tags:
        url = (f"{API}?site=stackoverflow&tagged={tag}&pagesize={min(limit, 30)}"
               f"&order=desc&sort=activity&filter=withbody")
        try:
            data = client.get(url, timeout=25).json()
        except Exception:
            continue
        for it in (data.get("items") or [])[:limit]:
            title = (it.get("title") or "").strip()
            link = it.get("link") or ""
            if not title or not link:
                continue
            body = it.get("body") or ""
            codes = snippets.extract_html(body)
            published = None
            ts = it.get("creation_date")
            if isinstance(ts, (int, float)):
                published = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(
                    timespec="seconds").replace("+00:00", "Z")
            summary = _strip_html(body)[:1500]
            recs.append(Record(
                url=link, title=title, published_at=published,
                summary=summary or None,
                content=(summary + snippets.render_block(codes))[:20000] or None,
                author=((it.get("owner") or {}).get("display_name")),
                category="troubleshooting",
                tags=["stackoverflow", tag] + tagging.classify(title, summary, body[:3000]),
                metrics={"score": it.get("score"), "answers": it.get("answer_count")},
                external_key=f"so:{it.get('question_id') or link}",
                extra={"origin_source": "stackoverflow", "tag": tag,
                       "code_snippets": codes[:10],
                       "is_answered": it.get("is_answered")},
            ))
    return recs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "06_techradar" / "data" / "techradar.db"))
    ap.add_argument("--tags", default=",".join(DEFAULT_TAGS))
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    policy = CrawlPolicy(timeout_seconds=25, max_retries=2, min_interval_seconds=2.0)
    client = HttpClient(policy)
    with IntelDB(Path(args.db)) as db:
        spec = SourceSpec(
            source_id="stackoverflow", source_name="Stack Overflow（排障问答）",
            source_type="api", channel="public",
            fetch=lambda: fetch(client, tags, args.limit),
            aggregator=None, origin_extra_key="origin_source")
        result = run_source(db, db.conn, spec)
        total = db.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    print(f"stackoverflow status={result['status']} fetched={result['fetched']} "
          f"inserted={result['inserted']} dedup={result['deduped']} error={result['error']}")
    print(f"库内条目 {total}")
    if args.report:
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
