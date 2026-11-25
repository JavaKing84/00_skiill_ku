#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_folo.py — 通道 B-1：Folo（Follow）认证采集适配器。

**接口依据与归属（重要）**
本适配器依据的是**第三方开源项目** `folo-mcp`（作者 Stephen Zhou / hyoban），
不是 Folo 官方发布的 MCP，也不是 Folo 官方公开文档化的 API：
  - 仓库：https://github.com/hyoban/folo-mcp
  - 版本：1.0.0（npm `folo-mcp`，MIT License）
  - 参考制品：npm tarball `folo-mcp-1.0.0.tgz`，SHA256 812CE7D8F0F70CA8B65D0EF6722E52BA5C70F53D9945A73D1DA818473E9510C1
  - 该实现通过浏览器 Cookie 会话访问 `https://api.follow.is` 的内部接口，
    属于**第三方对接口的观察与封装**，不是官方稳定 API。

真实接口（来自上述第三方实现）：
  Base : https://api.follow.is
  认证 : Cookie  __Secure-better-auth.session_token=<FOLO_SESSION_TOKEN>;
         User-Agent 浏览器 UA
  接口 : GET  /subscriptions?view=0            → 用户订阅的 feed 列表
         POST /entries  {view,feedId,limit,publishedAfter,withContent}
         GET  /feeds?id=|url=                    → feed 元信息
  响应封装：{code:0, data:...}；code!=0 视为失败并读取 message

**兼容风险**：这些端点与响应结构可能随 Folo 前端升级而变化，无版本化契约；
接口变更时需按线上实际响应重新适配（`_envelope` 与 `_entry_to_record` 已做防御式解析）。

增量：按 feed 记录 publishedAfter 水位（断点文件），只取新条目；失败可重试（水位不前移）。
安全：令牌只从环境变量/.env 读取，绝不写入代码、日志、数据库或报告；
     请勿把 Cookie 发送给任何 AI 助手，只在本地 `.env` 填写。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))

from skillkit.http import FetchError, HttpClient, env_present, load_dotenv  # noqa: E402
from skillkit.inteldb import IntelDB  # noqa: E402
from skillkit.pipeline import Record, SourceSpec, run_source  # noqa: E402
from skillkit.policy import CrawlPolicy  # noqa: E402
from skillkit.sources import ensure_registry, set_status, upsert_source  # noqa: E402

API = os.environ.get("FOLO_API_BASE", "https://api.follow.is").rstrip("/")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36")
CHECKPOINT = ROOT / "06_techradar" / "data" / "folo_checkpoint.json"

SETUP = (
    "配置方法：登录 https://app.folo.is → 浏览器开发者工具 → Network → 任一请求的 Request Headers → "
    "复制 Cookie 中 __Secure-better-auth.session_token= 的值 → "
    "写入 .env 的 FOLO_SESSION_TOKEN=（或设置同名环境变量）后重跑本脚本。"
)


def _cookie(token: str) -> str:
    return f"__Secure-better-auth.session_token={token};"


def _envelope(resp_json) -> dict:
    code = resp_json.get("code")
    if code not in (0, None):
        raise FetchError(f"Folo API 返回 code={code}: {resp_json.get('message')}", None, "auth")
    data = resp_json.get("data")
    return data if data is not None else resp_json


def _load_checkpoint() -> dict:
    if CHECKPOINT.exists():
        try:
            return json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_checkpoint(cp: dict) -> None:
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")


def _entry_to_record(entry: dict, feed_id: str) -> Record | None:
    """Folo 条目字段做防御式读取（不同版本字段名可能不同）。"""
    url = (entry.get("url") or entry.get("link") or "").strip()
    title = (entry.get("title") or entry.get("feedTitle") or "").strip()
    if not url.startswith("http") or not title:
        return None
    published = (entry.get("publishedAt") or entry.get("published_at") or "")
    content = entry.get("content") or entry.get("description") or entry.get("summary") or ""
    author = entry.get("author") or entry.get("authorName")
    if isinstance(author, dict):
        author = author.get("name") or author.get("handle")
    feed_title = entry.get("feedTitle") or entry.get("feed", {}).get("title") \
        if isinstance(entry.get("feed"), dict) else entry.get("feedTitle")
    return Record(
        url=url, title=title, published_at=published or None,
        summary=(content or "")[:4000] or None, content=(content or "")[:20000] or None,
        author=author if isinstance(author, str) else None,
        category="info",
        tags=["folo"] + ([str(feed_title)] if feed_title else []),
        external_key=f"folo:{entry.get('id') or url}",
        extra={"folo_entry_id": entry.get("id"), "folo_feed_id": feed_id,
               "folo_feed_title": feed_title,
               "origin_source": feed_title or url.split("://", 1)[-1].split("/", 1)[0].replace("www.", "")},
    )


def fetch(client: HttpClient, token: str, limit: int, max_feeds: int) -> list[Record]:
    headers = {"cookie": _cookie(token), "user-agent": UA, "content-type": "application/json"}
    subs = _envelope(client.get_json(f"{API}/subscriptions", params={"view": 0}, headers=headers))
    feeds = subs if isinstance(subs, list) else (subs.get("feeds") or subs.get("subscriptions") or [])
    cp = _load_checkpoint()
    recs: list[Record] = []
    for feed in feeds[:max_feeds]:
        feed_id = str(feed.get("id") or feed.get("feedId") or "")
        if not feed_id:
            continue
        body = {"view": 0, "feedId": feed_id, "limit": limit, "withContent": True}
        since = cp.get(feed_id)
        if since:
            body["publishedAfter"] = since
        try:
            data = _envelope(client.post(f"{API}/entries", json_body=body, headers=headers))
        except FetchError:
            continue                      # 单个 feed 失败不影响其它 feed
        items = data if isinstance(data, list) else (data.get("entries") or data.get("items") or [])
        newest = since
        for it in items:
            rec = _entry_to_record(it, feed_id)
            if rec is None:
                continue
            recs.append(rec)
            ts = rec.published_at
            if ts and (newest is None or ts > newest):
                newest = ts
        if newest and newest != since:
            cp[feed_id] = newest
    _save_checkpoint(cp)
    return recs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "06_techradar" / "data" / "techradar.db"))
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--max-feeds", type=int, default=10)
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    token = os.environ.get("FOLO_SESSION_TOKEN", "").strip()

    db_path = Path(args.db)
    with IntelDB(db_path) as db:
        ensure_registry(db.conn)
        upsert_source(db.conn, "folo", "Folo（用户订阅聚合）", "api", "authenticated",
                      auth_required=True, authorization_status="granted",
                      credential_status="missing" if not token else "valid",
                      status="AUTH_REQUIRED" if not token else "READY",
                      notes="令牌来自 Folo Web 会话 Cookie（__Secure-better-auth.session_token）")
        if not token:
            # 方案 A/B：无 API 令牌时，优先复用本机浏览器登录态（CDP + 持久化配置）
            try:
                from websession import WebSessionBlocked, WebSessionError, folo_fetch
                if os.environ.get("TECH_RADAR_DISABLE_BROWSER", "0") == "1":
                    raise RuntimeError("TECH_RADAR_DISABLE_BROWSER=1（测试/CI 禁用浏览器回退）")
                try:
                    recs = folo_fetch(limit=args.limit, max_feeds=args.max_feeds)
                except WebSessionBlocked as exc:
                    raise
                except WebSessionError as exc:
                    raise
                if not recs:
                    raise WebSessionError("浏览器会话未取到 Folo 条目（可能订阅为空或页面结构变化）")
                upsert_source(db.conn, "folo", "Folo（用户订阅聚合）", "api", "browser",
                              auth_required=True, authorization_status="granted",
                              credential_status="valid", connectivity_status="online",
                              status="READY",
                              notes="浏览器登录态采集（复用本机 Chrome 会话，无 API 令牌）")
                spec = SourceSpec(
                    source_id="folo", source_name="Folo（用户订阅聚合）", source_type="api",
                    channel="browser",
                    fetch=lambda: recs,
                    auth_required=True, authorization_status="granted", credential_status="valid",
                    aggregator="folo", origin_extra_key="origin_source")
                result = run_source(db, db.conn, spec)
                entries = db.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
                print(f"folo status={result['status']} channel=browser_session "
                      f"fetched={result['fetched']} inserted={result['inserted']} "
                      f"dedup={result['deduped']} error={result['error']}")
                print(f"SUMMARY collected={result['fetched']} inserted={result['inserted']} "
                      f"deduped={result['deduped']} failed={0 if result['status'] == 'READY' else 1}")
                print(f"库内条目 {entries}")
                if args.report:
                    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
                    Path(args.report).write_text(json.dumps(
                        {"channel": "browser-folo", "mode": "browser_session",
                         "result": result, "db_entries": entries},
                        ensure_ascii=False, indent=2), encoding="utf-8")
                return 0 if result["status"] == "READY" else 2
            except WebSessionBlocked as exc:
                reason = f"浏览器会话被拒绝：{exc}"
            except Exception as exc:  # 浏览器不可用/未登录/结构变化
                reason = f"{type(exc).__name__}: {exc}"
            set_status(db.conn, "folo", "AUTH_REQUIRED", credential_status="missing",
                       connectivity_status="unknown", last_error=reason[:300])
            print(f"BLOCKED: 未配置 FOLO_SESSION_TOKEN，浏览器登录态也不可用（{reason[:200]}）。")
            print(SETUP)
            print("其余通道不受影响（公开采集继续）。")
            if args.report:
                Path(args.report).write_text(json.dumps(
                    {"channel": "authenticated-folo", "status": "AUTH_REQUIRED",
                     "reason": "missing_credential_and_browser_unavailable",
                     "browser_error": reason[:300], "setup": SETUP,
                     "inserted": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
            return 3

        policy = CrawlPolicy(timeout_seconds=25, max_retries=3, min_interval_seconds=1.0)
        client = HttpClient(policy, user_agent=UA)
        spec = SourceSpec(
            source_id="folo", source_name="Folo（用户订阅聚合）", source_type="api",
            channel="authenticated",
            fetch=lambda: fetch(client, token, args.limit, args.max_feeds),
            auth_required=True, authorization_status="granted", credential_status="valid",
            aggregator="folo", origin_extra_key="origin_source")
        result = run_source(db, db.conn, spec)
        entries = db.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    print(f"folo status={result['status']} fetched={result['fetched']} inserted={result['inserted']} "
          f"dedup={result['deduped']} error={result['error']}")
    print(f"SUMMARY collected={result['fetched']} inserted={result['inserted']} "
          f"deduped={result['deduped']} failed={0 if result['status'] == 'READY' else 1}")
    print(f"库内条目 {entries}")
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(
            {"channel": "authenticated-folo", "result": result, "db_entries": entries},
            ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
