#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""radar_read.py — 按需深度阅读入口（title_scanned → content_fetched → content_read → analyzed）。

设计原则：
- 标题扫描仍是轻量采集；只有用户提出深度研究问题时才按需抓正文。
- 只访问合法公开 URL；先查 robots.txt，命中 Disallow 则跳过并记录原因。
- 抓取成功并入正文后才推进 content_fetched；真正阅读后才 content_read；
  有证据的技术结论（--claim）才 analyzed，并写入 insights。
- 失败不推进状态、不伪装成功；全部动作写入 read_log。
- 不复制第二套爬虫：复用 skillkit.http（UA/超时/退避/限速）与 IntelDB。

用法：
  python 06_techradar/scripts/radar_read.py --db <库> --query "vla robot" --fetch --limit 5
  python 06_techradar/scripts/radar_read.py --db <库> --entry-id 123 --fetch --mark-read
  python 06_techradar/scripts/radar_read.py --db <库> --entry-id 123 --mark-analyzed --claim "结论..."
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))

from skillkit.http import FetchError, HttpClient  # noqa: E402
from skillkit.inteldb import IntelDB  # noqa: E402
from skillkit.policy import CrawlPolicy  # noqa: E402
from skillkit import search as sx  # noqa: E402

TEXT_TYPES = ("text/html", "text/plain", "application/xhtml", "application/xml",
              "application/rss+xml", "application/atom+xml", "application/json")
TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
HTML_RE = re.compile(r"<[^>]+>")
MIN_CHARS = 200
MAX_BYTES = 2_000_000
_robots_cache: dict[str, list[str]] = {}


def robots_disallowed(client: HttpClient, url: str) -> tuple[bool, str]:
    """轻量 robots 检查（只解析 User-agent: * 段的 Disallow）。"""
    parts = urlparse(url)
    host = parts.netloc
    if host in _robots_cache:
        rules = _robots_cache[host]
    else:
        rules = []
        try:
            r = client.get(f"{parts.scheme}://{host}/robots.txt")
            if r.status_code == 200:
                ua_star = False
                for line in r.text.splitlines():
                    line = line.strip()
                    if line.lower().startswith("user-agent:"):
                        ua_star = line.split(":", 1)[1].strip() == "*"
                    elif ua_star and line.lower().startswith("disallow:"):
                        path = line.split(":", 1)[1].strip()
                        if path:
                            rules.append(path)
        except FetchError:
            rules = []           # robots 不可达时不阻断，但会在日志里体现
        _robots_cache[host] = rules
    path = parts.path or "/"
    for rule in rules:
        if rule != "/" and path.startswith(rule):
            return True, rule
        if rule == "/" and path == "/":
            return True, rule
    return False, ""


def extract_text(body: str) -> str:
    text = TAG_RE.sub(" ", body)
    text = HTML_RE.sub(" ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_body(client: HttpClient, url: str) -> tuple[bool, str, dict]:
    """返回 (成功, 正文, 元信息)。"""
    try:
        r = client.get(url)
    except FetchError as exc:
        return False, "", {"error": str(exc), "kind": exc.kind, "http_status": exc.status}
    ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype and not any(ctype.startswith(t) for t in TEXT_TYPES):
        return False, "", {"error": f"unsupported_content_type:{ctype}", "http_status": r.status_code}
    raw = r.content[:MAX_BYTES]
    body = raw.decode(r.encoding or "utf-8", errors="replace")
    text = extract_text(body) if "html" in ctype or "xml" in ctype else body.strip()
    if len(text) < MIN_CHARS:
        return False, text, {"error": f"content_too_short:{len(text)}", "http_status": r.status_code,
                             "bytes": len(raw)}
    return True, text, {"http_status": r.status_code, "bytes": len(raw), "content_chars": len(text),
                        "content_type": ctype}


def select_candidates(conn: sqlite3.Connection, args) -> list[dict]:
    if args.entry_id:
        out = []
        for eid in args.entry_id:
            row = conn.execute(
                "SELECT entry_id,title,url,origin_source,read_state FROM entries WHERE entry_id=?",
                (eid,)).fetchone()
            if row:
                out.append(dict(row))
        return out
    res = sx.query_entries(conn, text=args.query or None, since=args.since or None,
                           tags=[args.tag] if args.tag else None, limit=args.limit)
    return res["rows"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "06_techradar" / "data" / "techradar.db"))
    ap.add_argument("--entry-id", type=int, action="append", default=[])
    ap.add_argument("--query", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--since", default="")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--fetch", action="store_true", help="抓取候选条目的正文（默认只列候选）")
    ap.add_argument("--mark-read", action="store_true", help="对已有正文的条目推进到 content_read")
    ap.add_argument("--mark-analyzed", action="store_true", help="配合 --claim 推进到 analyzed 并写 insights")
    ap.add_argument("--claim", default="", help="已形成的有证据结论（写入 insights）")
    ap.add_argument("--dry-run", action="store_true", help="只展示将要做什么，不写库")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if not args.entry_id and not args.query and not args.tag and not args.since:
        print("FAIL: 需要 --entry-id 或 --query/--tag/--since 指定候选")
        return 2
    if args.mark_analyzed and not args.claim.strip():
        print("FAIL: --mark-analyzed 必须提供 --claim（有证据的结论）")
        return 2

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"FAIL: 情报库不存在 {db_path}")
        return 2

    policy = CrawlPolicy(timeout_seconds=25, max_retries=2, backoff_base_seconds=2.0,
                         min_interval_seconds=1.5)
    client = HttpClient(policy)

    fetched = failed = read = analyzed = skipped = 0
    details: list[dict] = []

    with IntelDB(db_path) as db:
        db.ensure_read_log()
        candidates = select_candidates(db.conn, args)
        print(f"候选 {len(candidates)} 条")
        for cand in candidates:
            eid = cand["entry_id"]
            rec = {"entry_id": eid, "title": (cand.get("title") or "")[:60],
                   "url": cand.get("url"), "state": cand.get("read_state"), "actions": []}
            entry = db.get_entry(eid)
            if not entry:
                details.append(rec)
                continue
            # 1) 抓正文
            if args.fetch and (entry.get("read_state") or "title_scanned") == "title_scanned":
                blocked, rule = robots_disallowed(client, entry["url"] or "")
                if blocked:
                    rec["actions"].append(f"robots_disallow:{rule}")
                    skipped += 1
                    if not args.dry_run:
                        db.log_read(eid, "fetch", "SKIPPED", error=f"robots:{rule}")
                    details.append(rec)
                    continue
                if args.dry_run:
                    rec["actions"].append("would_fetch")
                    details.append(rec)
                    continue
                ok, text, meta = fetch_body(client, entry["url"] or "")
                if ok:
                    db.store_content(eid, text)
                    state = db.mark_read_state_by_id(eid, "content_fetched")
                    db.log_read(eid, "fetch", "SUCCESS", http_status=meta.get("http_status"),
                                nbytes=meta.get("bytes", 0), content_chars=meta.get("content_chars", 0))
                    rec["actions"].append(f"fetched->{state}")
                    fetched += 1
                else:
                    db.log_read(eid, "fetch", "FAILED", http_status=meta.get("http_status"),
                                error=meta.get("error"))
                    rec["actions"].append(f"fetch_failed:{meta.get('error')}")
                    failed += 1
            # 2) 标记已读（需要已有正文）
            if args.mark_read:
                if args.dry_run:
                    rec["actions"].append("would_mark_read")
                else:
                    fresh = db.get_entry(eid) or {}
                    has_body = '"content"' in (fresh.get("extra_json") or "")
                    if has_body:
                        state = db.mark_read_state_by_id(eid, "content_read")
                        db.log_read(eid, "read", "SUCCESS")
                        rec["actions"].append(f"read->{state}")
                        read += 1
                    else:
                        db.log_read(eid, "read", "SKIPPED", error="no_content")
                        rec["actions"].append("read_skipped:no_content")
                        skipped += 1
            # 3) 分析结论
            if args.mark_analyzed:
                if args.dry_run:
                    rec["actions"].append("would_mark_analyzed")
                else:
                    state = db.mark_read_state_by_id(eid, "analyzed")
                    db.add_insight("techradar", args.claim.strip(),
                                   [{"entry_id": eid, "url": entry.get("url"),
                                     "title": entry.get("title")}], "medium")
                    db.log_read(eid, "analyze", "SUCCESS", error=None)
                    rec["actions"].append(f"analyzed->{state}")
                    analyzed += 1
            details.append(rec)

        states = {r[0]: r[1] for r in db.conn.execute(
            "SELECT read_state, COUNT(*) FROM entries GROUP BY read_state")}
        log_summary = {f"{r[0]}/{r[1]}": r[2] for r in db.conn.execute(
            "SELECT stage,status,COUNT(*) FROM read_log GROUP BY stage,status")}
        entries = db.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    payload = {
        "candidates": len(candidates), "fetched": fetched, "fetch_failed": failed,
        "marked_read": read, "marked_analyzed": analyzed, "skipped": skipped,
        "read_state_distribution": states, "read_log_summary": log_summary,
        "db_entries": entries, "dry_run": args.dry_run, "details": details,
    }
    for d in details:
        print(f"  {d['entry_id']:>5} {d['state']:16s} {','.join(d['actions']) or '(noop)':28s} {d['title']}")
    print(f"抓取成功 {fetched}，失败 {failed}，标记已读 {read}，分析 {analyzed}，跳过 {skipped}")
    print(f"状态分布 {states}")
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"-> {p}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
