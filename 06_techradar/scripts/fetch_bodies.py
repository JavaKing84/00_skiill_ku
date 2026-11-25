#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_bodies.py — 正文回源抓取（RSS 只是目录，正文必须回源拿）。

为什么需要这一步：RSS / API 给的是标题 + 一两句摘要（本库实测平均 254 字符），
真正有用的东西——PoC 细节、受影响版本、组织归因、修复建议——都在文章正文里。
只存摘要等于存了个书签，检索命中后还得再点一次链接。

流程：挑出「有 URL 但无正文」的条目 → 三级通道回退抓 HTML → 正文抽取 → 落 article_bodies。

通道回退（与 sec_restricted 同一套思路）：
    HttpClient（快、限速）→ curl_cffi 浏览器指纹 → 无头浏览器 → 放弃并记录原因

用法：
  python 06_techradar/scripts/fetch_bodies.py --db 06_techradar/data/techradar.db --limit 20
  python 06_techradar/scripts/fetch_bodies.py --db ... --category security --since 2026-11-01
  python 06_techradar/scripts/fetch_bodies.py --db ... --retry-failed    # 重试上次失败的
  python 06_techradar/scripts/fetch_bodies.py --db ... --stats           # 只看统计，不抓
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))
sys.path.insert(0, str(ROOT / "01_crawler" / "scripts"))

from skillkit.http import FetchError, HttpClient  # noqa: E402
from skillkit.inteldb import IntelDB  # noqa: E402
from skillkit.policy import CrawlPolicy  # noqa: E402

MIN_CHARS = 200          # 短于此判为 too_short：导航页 / 付费墙 / 反爬占位
MAX_CHARS = 120_000      # 截断上限，防止把整站 HTML 灌进库


def _is_html(raw: str) -> bool:
    head = raw[:1200].lower()
    return "<html" in head or "<!doctype" in head or "<body" in head


def _extract(raw: str) -> tuple[str, str]:
    """trafilatura → readability → builtin 三级抽取（extract_article 内已实现）。"""
    from extract_article import extract

    return extract(raw)


def _fetch_http(client: HttpClient, url: str) -> tuple[str, str, int]:
    """第一级：普通 HTTP（带 UA、限速）。"""
    r = client.get(url, timeout=20)
    return r.text, "http", r.status_code


def _fetch_impersonated(url: str) -> tuple[str, str, int]:
    """第二级：浏览器 TLS 指纹（curl_cffi）。"""
    from curl_cffi import requests as curl_requests

    r = curl_requests.get(url, impersonate="chrome", timeout=25)
    if r.status_code >= 400:
        raise FetchError(f"HTTP {r.status_code}: {url}", r.status_code, "http")
    return r.text, "impersonate", r.status_code


def fetch_one(client: HttpClient, browser_factory, url: str) -> dict:
    """抓一条正文，返回落库所需字段。任何异常都转成状态而不抛出。"""
    raw, via, status = "", None, None
    errors: list[str] = []

    for name, fn in (("http", lambda: _fetch_http(client, url)),
                     ("impersonate", lambda: _fetch_impersonated(url))):
        try:
            raw, via, status = fn()
            if raw:
                break
        except Exception as exc:                      # noqa: BLE001 —— 逐级降级
            errors.append(f"{name}:{type(exc).__name__}:{str(exc)[:80]}")

    if not raw:
        browser = browser_factory()                   # 第三级：无头浏览器
        try:
            if browser is not None and browser.available:
                raw, via, status = browser.get_text(url), "browser", 200
        except Exception as exc:                      # noqa: BLE001
            errors.append(f"browser:{type(exc).__name__}:{str(exc)[:80]}")

    base = {"url": url, "http_status": status, "via": via,
            "fetched_at": datetime.now().isoformat(timespec="seconds")}

    if not raw:
        return {**base, "status": "blocked", "engine": None, "char_len": 0,
                "body": None, "error": "; ".join(errors)[:400]}
    if not _is_html(raw):
        return {**base, "status": "not_html", "engine": None, "char_len": 0,
                "body": None, "error": "返回非 HTML（PDF/JSON/拦截跳转）"[:400]}

    text, engine = _extract(raw)
    # 代码块加权：<pre><code> 常被正文抽取器丢弃，但对排障检索价值最高，单独追加。
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import snippets
        text = (text or "") + snippets.render_block(snippets.extract_html(raw))
    except Exception:
        pass
    text = (text or "").strip()[:MAX_CHARS]
    if len(text) < MIN_CHARS:
        return {**base, "status": "too_short", "engine": engine, "char_len": len(text),
                "body": text or None, "error": f"正文仅 {len(text)} 字符（付费墙/反爬占位/导航页）"}
    return {**base, "status": "ok", "engine": engine, "char_len": len(text),
            "body": text, "error": None}


def _pending(conn: sqlite3.Connection, category: str | None, since: str | None,
             retry_failed: bool, limit: int) -> list[sqlite3.Row]:
    """挑出待抓条目：无正文行；retry_failed 时连失败的也纳入。"""
    sql = ["SELECT e.entry_id, e.url, e.title FROM entries e "
           "LEFT JOIN article_bodies b ON b.entry_id = e.entry_id "
           "WHERE e.url IS NOT NULL AND e.url <> ''"]
    args: list = []
    if retry_failed:
        sql.append("AND (b.entry_id IS NULL OR b.status <> 'ok')")
    else:
        sql.append("AND b.entry_id IS NULL")
    if category:
        sql.append("AND e.category = ?")
        args.append(category)
    if since:
        sql.append("AND e.published_at >= ?")
        args.append(since)
    sql.append("ORDER BY e.published_at DESC LIMIT ?")
    args.append(limit)
    return conn.execute(" ".join(sql), args).fetchall()


def _save(conn: sqlite3.Connection, entry_id: int, rec: dict) -> None:
    conn.execute(
        "INSERT INTO article_bodies(entry_id,url,status,engine,via,char_len,body,"
        "http_status,error,attempts,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,1,?) "
        "ON CONFLICT(entry_id) DO UPDATE SET status=excluded.status, engine=excluded.engine, "
        "via=excluded.via, char_len=excluded.char_len, body=excluded.body, "
        "http_status=excluded.http_status, error=excluded.error, "
        "attempts=article_bodies.attempts+1, fetched_at=excluded.fetched_at",
        (entry_id, rec["url"], rec["status"], rec["engine"], rec["via"], rec["char_len"],
         rec["body"], rec["http_status"], rec["error"], rec["fetched_at"]))
    conn.commit()
    _reindex(conn, entry_id)


def _advance_read_state(db: IntelDB, conn: sqlite3.Connection, entry_id: int, rec: dict) -> str:
    """正文落库后同步阅读状态：成功推进到 content_fetched，并写 read_log。

    只前进不降级：已 content_read / analyzed 的条目不会被改回。
    """
    if rec.get("status") != "ok":
        db.log_read(entry_id, "fetch", "FAILED", http_status=rec.get("http_status"),
                    error=rec.get("error"))
        return "skipped"
    final = db.mark_read_state_by_id(entry_id, "content_fetched")
    db.log_read(entry_id, "fetch", "SUCCESS", http_status=rec.get("http_status"),
                content_chars=int(rec.get("char_len") or 0))
    return final


def _sync_read_state(db: IntelDB, conn: sqlite3.Connection) -> dict:
    """回填历史正文的阅读状态：status=ok 但仍是 title_scanned 的条目推进到 content_fetched。

    幂等：已推进的条目不会重复写 read_log。
    """
    rows = conn.execute(
        "SELECT b.entry_id, b.char_len, b.http_status FROM article_bodies b "
        "JOIN entries e ON e.entry_id=b.entry_id "
        "WHERE b.status='ok' AND (e.read_state IS NULL OR e.read_state='title_scanned')"
    ).fetchall()
    db.ensure_read_log()
    advanced = 0
    logged = 0
    for row in rows:
        final = db.mark_read_state_by_id(int(row["entry_id"]), "content_fetched")
        if final == "content_fetched":
            advanced += 1
        exists = conn.execute(
            "SELECT 1 FROM read_log WHERE entry_id=? AND stage='fetch' AND status='SUCCESS' LIMIT 1",
            (row["entry_id"],)).fetchone()
        if not exists:
            db.log_read(int(row["entry_id"]), "fetch", "SUCCESS",
                        http_status=row["http_status"],
                        content_chars=int(row["char_len"] or 0))
            logged += 1
    return {"candidates": len(rows), "advanced": advanced, "logged": logged}


def _reindex(conn: sqlite3.Connection, entry_id: int) -> None:
    """正文入库后立刻重刷 FTS：否则全文检索搜不到刚抓的正文。

    index_entry 会优先取 article_bodies.body，失败不影响主流程。
    """
    try:
        from skillkit.search import index_entry

        row = conn.execute("SELECT * FROM entries WHERE entry_id=?", (entry_id,)).fetchone()
        if row is not None:
            index_entry(conn, row)
            conn.commit()
    except Exception:                      # noqa: BLE001 —— 索引失败不该丢正文
        pass


def _print_stats(conn: sqlite3.Connection) -> None:
    total = conn.execute("select count(*) from entries").fetchone()[0]
    rows = conn.execute("select status, count(*) from article_bodies group by 1").fetchall()
    have = dict(rows)
    done = sum(have.values())
    print(f"条目总数 {total}｜已处理 {done}｜未处理 {total - done}")
    for status, cnt in sorted(have.items(), key=lambda x: -x[1]):
        print(f"  {status:<12}{cnt:>5}")
    ok = conn.execute("select count(*), avg(char_len) from article_bodies "
                      "where status='ok'").fetchone()
    if ok and ok[0]:
        print(f"正文均值 {int(ok[1] or 0)} 字符（{ok[0]} 篇）")
    print("通道分布：", dict(conn.execute(
        "select via, count(*) from article_bodies where status='ok' group by 1").fetchall()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--category", default="security",
                    help="按分类抓取；空字符串表示全部（PowerShell 会吞掉空串，建议用 --all）")
    ap.add_argument("--all", action="store_true", help="抓取全部分类（等价 --category=）")
    ap.add_argument("--since", default="")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--sync-read-state", action="store_true",
                    help="回填历史正文的 read_state：status=ok 的条目推进到 content_fetched")
    ap.add_argument("--report", default="")
    ap.add_argument("--no-browser", action="store_true",
                    help="禁用无头浏览器（第三级），纯 HTTP 环境用")
    args = ap.parse_args()
    if args.all:
        args.category = ""

    db = IntelDB(args.db)
    conn = db.conn

    if args.sync_read_state:
        synced = _sync_read_state(db, conn)
        print(f"read_state 回填：candidates={synced['candidates']} "
              f"advanced={synced['advanced']} logged={synced['logged']}")
        if not args.stats:
            db.close()
            return 0

    if args.stats:
        _print_stats(conn)
        db.close()
        return 0

    rows = _pending(conn, args.category or None, args.since or None,
                    args.retry_failed, args.limit)
    if not rows:
        print("没有待抓条目（都已有正文；要重抓失败项加 --retry-failed）")
        _print_stats(conn)
        db.close()
        return 0

    client = HttpClient(CrawlPolicy(timeout_seconds=20, max_retries=0,
                                   backoff_base_seconds=1.0, min_interval_seconds=1.0))
    browser = None
    used_browser = 0

    def browser_factory():
        """懒创建：只在 HTTP 与指纹都失败时才启动浏览器，且整个批次复用。"""
        nonlocal browser
        if args.no_browser:
            return None
        if browser is None:
            from public_sources import _BrowserFetch
            browser = _BrowserFetch()
            if not browser.available:
                print("  [提示] 浏览器通道不可用（playwright 或内核缺失），仅用前两级")
        return browser

    print(f"待抓 {len(rows)} 条（category={args.category or '全部'}，"
          f"since={args.since or '-'}）")
    results: list[dict] = []
    t0 = time.time()
    for i, row in enumerate(rows, 1):
        t = time.time()
        rec = fetch_one(client, browser_factory, row["url"])
        results.append({**rec, "entry_id": row["entry_id"], "title": row["title"][:70]})
        _save(conn, row["entry_id"], rec)
        _advance_read_state(db, conn, row["entry_id"], rec)
        if rec["via"] == "browser":
            used_browser += 1
        flag = "OK " if rec["status"] == "ok" else rec["status"][:8]
        print(f"[{i}/{len(rows)}] {flag:<9}{rec['char_len']:>6}字 "
              f"{str(rec['via']):<12}{time.time()-t:4.1f}s {row['title'][:48]}")

    if browser is not None:
        browser.close()

    tally = Counter(r["status"] for r in results)
    total_chars = sum(r["char_len"] for r in results if r["status"] == "ok")
    print(f"\n耗时 {time.time()-t0:.1f}s｜" + "  ".join(f"{k}={v}" for k, v in tally.items()))
    print(f"正文合计 {total_chars} 字符｜浏览器通道 {used_browser} 次")
    _print_stats(conn)

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(
            {"generated_at": datetime.now().isoformat(timespec="seconds"),
             "tally": dict(tally), "results": results},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"-> {args.report}")

    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
