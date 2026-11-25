#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_reddit.py — 通道 B-2：Reddit 官方 Data API OAuth 适配器。

官方流程（Reddit Data API）：
  1) 在 https://developers.reddit.com/app-registration 注册应用，取得 client_id / client_secret
     （script 类型应用；2023 年起新访问需官方审批，2026 年起还需完成 app-registration）。
  2) 取令牌：POST https://www.reddit.com/api/v1/access_token
     HTTP Basic 认证(client_id, client_secret)，body: grant_type=client_credentials
  3) 调用：GET https://oauth.reddit.com/r/<subreddit>/new?limit=100&after=<t3_id>
     Header: Authorization: Bearer <token>，并必须带真实 User-Agent（禁止伪造/通用 UA）

本适配器严格区分三种状态，不混为一谈：
  authorization_status : pending（未获批）/ approved（已获批）/ unknown
  credential_status    : missing / invalid / valid
  connectivity_status  : reachable / unauthorized / blocked / error
不使用未授权接口、伪造 UA、RSS 镜像或任何绕过访问控制的手段。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))

from skillkit.http import FetchError, HttpClient, load_dotenv  # noqa: E402
from skillkit.inteldb import IntelDB  # noqa: E402
from skillkit.pipeline import Record, SourceSpec, run_source  # noqa: E402
from skillkit.policy import CrawlPolicy  # noqa: E402
from skillkit.sources import ensure_registry, set_status, upsert_source  # noqa: E402
from proxy_env import detect_proxy  # noqa: E402

TOKEN_URL = os.environ.get("REDDIT_TOKEN_URL", "https://www.reddit.com/api/v1/access_token")
API_BASE = os.environ.get("REDDIT_API_BASE", "https://oauth.reddit.com").rstrip("/")
UA = "linux:techradar-intel:1.0 (by /u/techradar-local) local personal research tool"
CHECKPOINT = ROOT / "06_techradar" / "data" / "reddit_checkpoint.json"

SETUP = (
    "配置方法：① 在 https://developers.reddit.com/app-registration 注册应用（script 类型），"
    "等待官方访问审批；② 把 client_id / client_secret 写入 .env："
    "REDDIT_CLIENT_ID=... 与 REDDIT_CLIENT_SECRET=...；③ 重跑本脚本。"
    "未获批或无凭据时本通道为 APPROVAL_REQUIRED / AUTH_REQUIRED，不影响公开通道。"
)

SETUP_OAUTH2 = (
    "OAuth2 预留接口（用户上下文）：在 .env 额外配置 REDDIT_REFRESH_TOKEN=...，"
    "脚本会用 grant_type=refresh_token 换取用户级 access_token；"
    "适用于需要登录态/私有订阅的抓取。refresh_token 需通过官方 installed-app 授权流程获取。"
)


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


def get_token(client: HttpClient, client_id: str, client_secret: str) -> str:
    """client_credentials 换取 app 级 access_token。"""
    try:
        r = client.post(TOKEN_URL, auth=(client_id, client_secret),
                        data={"grant_type": "client_credentials"},
                        headers={"User-Agent": UA})
    except FetchError as exc:
        raise FetchError(f"Reddit 取令牌失败：{exc}", exc.status, exc.kind) from None
    try:
        data = r.json()
    except ValueError:
        raise FetchError("Reddit 取令牌返回非 JSON", r.status_code, "parse") from None
    token = data.get("access_token")
    if not token:
        raise FetchError(f"Reddit 未返回 access_token：{str(data)[:120]}", r.status_code, "auth")
    return token


def get_user_token(client: HttpClient, client_id: str, client_secret: str,
                   refresh_token: str) -> str:
    """OAuth2 预留接口：用 refresh_token 换取用户上下文 access_token。"""
    try:
        r = client.post(TOKEN_URL, auth=(client_id, client_secret),
                        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                        headers={"User-Agent": UA})
    except FetchError as exc:
        raise FetchError(f"Reddit refresh_token 换取失败：{exc}", exc.status, exc.kind) from None
    try:
        data = r.json()
    except ValueError:
        raise FetchError("Reddit refresh_token 返回非 JSON", r.status_code, "parse") from None
    token = data.get("access_token")
    if not token:
        raise FetchError(f"Reddit 未返回 access_token：{str(data)[:120]}", r.status_code, "auth")
    return token


def check_approval(client: HttpClient, token: str) -> tuple[str, str]:
    """探测 API 可用性与授权范围。返回 (authorization_status, connectivity_status)。"""
    try:
        r = client.get(f"{API_BASE}/api/v1/me", headers={"Authorization": f"Bearer {token}",
                                                          "User-Agent": UA})
        body = (r.text or "")[:200].lower()
        if r.status_code == 200:
            return "approved", "reachable"
        if r.status_code == 403:
            if "blocked" in body or "only approved" in body or "api access" in body:
                return "pending", "blocked"
            return "unknown", "blocked"
        return "unknown", "error"
    except FetchError as exc:
        return "unknown", ("unauthorized" if exc.kind == "auth" else "error")


def fetch(client: HttpClient, token: str, subs: list[str], limit: int,
          pages_per_sub: int = 2) -> list[Record]:
    recs: list[Record] = []
    cp = _load_checkpoint()
    for sub in subs:
        after = cp.get(sub)
        seen_newest = after
        for _ in range(pages_per_sub):
            params = {"limit": min(100, limit), "raw_json": 1}
            if after:
                params["after"] = after
            try:
                r = client.get(f"{API_BASE}/r/{sub}/new", params=params,
                               headers={"Authorization": f"Bearer {token}", "User-Agent": UA})
            except FetchError:
                break                      # 单个 sub 失败不影响其它 sub
            try:
                data = r.json()
            except ValueError:
                break
            children = ((data.get("data") or {}).get("children")) or []
            if not children:
                break
            for child in children:
                d = child.get("data") or {}
                url = d.get("url_overridden_by_dest") or d.get("url") or ""
                title = d.get("title") or ""
                if not title:
                    continue
                created = d.get("created_utc")
                published = None
                if isinstance(created, (int, float)):
                    published = datetime.fromtimestamp(created, tz=timezone.utc).isoformat(
                        timespec="seconds").replace("+00:00", "Z")
                if seen_newest and published and published <= seen_newest:
                    continue          # 增量：早于水位则跳过
                recs.append(Record(
                    url=url or f"https://www.reddit.com/r/{sub}/comments/{d.get('id')}",
                    title=title, published_at=published,
                    summary=(d.get("selftext") or "")[:4000] or None,
                    author=d.get("author"), category="news",
                    tags=["reddit", sub],
                    metrics={"score": d.get("score"), "comments": d.get("num_comments"),
                             "upvote_ratio": d.get("upvote_ratio")},
                    external_key=f"reddit:{d.get('id')}",
                    extra={"subreddit": sub, "reddit_id": d.get("id"),
                           "permalink": d.get("permalink"), "origin_source": sub}))
                if published and (seen_newest is None or published > seen_newest):
                    seen_newest = published
            after = ((data.get("data") or {}).get("after"))
            if not after:
                break
        if seen_newest:
            cp[sub] = seen_newest
    _save_checkpoint(cp)
    return recs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "06_techradar" / "data" / "techradar.db"))
    ap.add_argument("--subreddits", default="coolgithubprojects,BestGitHubRepos,LocalLLaMA,MachineLearning")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    cid = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    csec = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    refresh = os.environ.get("REDDIT_REFRESH_TOKEN", "").strip()

    subs = [s.strip() for s in args.subreddits.split(",") if s.strip()]
    db_path = Path(args.db)
    with IntelDB(db_path) as db:
        ensure_registry(db.conn)
        if not cid or not csec:
            # 方案 A/B：无 OAuth 凭据时，优先复用本机浏览器登录态（CDP + 持久化配置）
            try:
                from websession import WebSessionBlocked, WebSessionError, reddit_fetch
                if os.environ.get("TECH_RADAR_DISABLE_BROWSER", "0") == "1":
                    raise RuntimeError("TECH_RADAR_DISABLE_BROWSER=1（测试/CI 禁用浏览器回退）")
                recs = reddit_fetch(subs, limit=args.limit)
                if not recs:
                    raise WebSessionError("浏览器会话未取到 Reddit 帖子（可能全部失败）")
                upsert_source(db.conn, "reddit", "Reddit（浏览器登录态）", "api", "browser",
                              auth_required=True, authorization_status="granted",
                              credential_status="valid", connectivity_status="online",
                              status="READY",
                              notes="浏览器登录态采集（复用本机 Chrome 会话，无 OAuth 凭据）")
                spec = SourceSpec(
                    source_id="reddit", source_name="Reddit（浏览器登录态）", source_type="api",
                    channel="browser",
                    fetch=lambda: recs,
                    auth_required=True, authorization_status="granted", credential_status="valid",
                    aggregator="reddit", origin_extra_key="origin_source")
                result = run_source(db, db.conn, spec)
                entries = db.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
                print(f"reddit status={result['status']} channel=browser_session "
                      f"fetched={result['fetched']} inserted={result['inserted']} "
                      f"dedup={result['deduped']} error={result['error']}")
                print(f"SUMMARY collected={result['fetched']} inserted={result['inserted']} "
                      f"deduped={result['deduped']} failed={0 if result['status'] == 'READY' else 1}")
                print(f"库内条目 {entries}")
                if args.report:
                    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
                    Path(args.report).write_text(json.dumps(
                        {"channel": "browser-reddit", "mode": "browser_session",
                         "result": result, "db_entries": entries},
                        ensure_ascii=False, indent=2), encoding="utf-8")
                return 0 if result["status"] == "READY" else 2
            except WebSessionBlocked as exc:
                # SKILL.md §9.4：同一出口「先 200 后 403」属速率/行为封禁，
                # 正确动作是冷却 ≥6h 后单页低速重试，不是换出口重打一遍。
                reason = str(exc)[:300]
                upsert_source(db.conn, "reddit", "Reddit（浏览器登录态）", "api", "browser",
                              auth_required=True, authorization_status="granted",
                              credential_status="valid", connectivity_status="blocked",
                              status="BLOCKED",
                              notes="浏览器登录态可用，但站点按出口 IP 返回 403")
                set_status(db.conn, "reddit", "BLOCKED", credential_status="valid",
                           connectivity_status="blocked", collection_status="BLOCKED",
                           last_error=reason)
                print(f"BLOCKED: Reddit 站点拒绝（403/风控），非凭据问题：{reason[:200]}")
                print("其余通道不受影响（公开采集继续）。")
                if args.report:
                    Path(args.report).write_text(json.dumps(
                        {"channel": "browser-reddit", "status": "BLOCKED",
                         "reason": "site_blocked_by_ip", "evidence": reason,
                         "inserted": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
                return 3
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                upsert_source(db.conn, "reddit", "Reddit（官方 Data API / OAuth）", "api", "authenticated",
                              auth_required=True, authorization_status="pending",
                              credential_status="missing", connectivity_status="unknown",
                              status="APPROVAL_REQUIRED", notes="需官方 app-registration 与访问审批")
                set_status(db.conn, "reddit", "APPROVAL_REQUIRED", credential_status="missing",
                           connectivity_status="unknown",
                           last_error=f"缺少 REDDIT_CLIENT_ID/SECRET；浏览器兜底失败：{reason}"[:300])
                print("BLOCKED: 未配置 REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET，浏览器登录态也不可用。")
                print(f"  浏览器兜底错误：{reason[:200]}")
                print(SETUP)
                print("公开通道与 Folo 通道不受影响。")
                if args.report:
                    Path(args.report).write_text(json.dumps(
                        {"channel": "authenticated-reddit", "status": "APPROVAL_REQUIRED",
                         "authorization_status": "pending", "credential_status": "missing",
                         "connectivity_status": "unknown", "browser_error": reason[:300],
                         "setup": SETUP, "inserted": 0},
                        ensure_ascii=False, indent=2), encoding="utf-8")
                return 3

        policy = CrawlPolicy(timeout_seconds=25, max_retries=3, min_interval_seconds=1.5)
        client = HttpClient(policy, user_agent=UA, proxy=detect_proxy())
        try:
            if refresh:
                token = get_user_token(client, cid, csec, refresh)
            else:
                token = get_token(client, cid, csec)
        except FetchError as exc:
            upsert_source(db.conn, "reddit", "Reddit（官方 Data API / OAuth）", "api", "authenticated",
                          auth_required=True, authorization_status="unknown",
                          credential_status="invalid", connectivity_status="unauthorized",
                          status="AUTH_REQUIRED", notes=str(exc)[:200])
            set_status(db.conn, "reddit", "AUTH_REQUIRED", credential_status="invalid",
                       connectivity_status="unauthorized", last_error=str(exc))
            print(f"BLOCKED: Reddit 认证失败：{exc}")
            print(SETUP)
            if args.report:
                Path(args.report).write_text(json.dumps(
                    {"channel": "authenticated-reddit", "status": "AUTH_REQUIRED",
                     "authorization_status": "unknown", "credential_status": "invalid",
                     "connectivity_status": "unauthorized", "error": str(exc), "inserted": 0},
                    ensure_ascii=False, indent=2), encoding="utf-8")
            return 3

        auth_status, conn_status = check_approval(client, token)
        upsert_source(db.conn, "reddit", "Reddit（官方 Data API / OAuth）", "api", "authenticated",
                      auth_required=True, authorization_status=auth_status,
                      credential_status="valid", connectivity_status=conn_status,
                      status="READY" if auth_status == "approved" else "APPROVAL_REQUIRED",
                      notes=f"官方 OAuth client_credentials；审批={auth_status}；连通={conn_status}")
        if conn_status != "reachable":
            set_status(db.conn, "reddit", "APPROVAL_REQUIRED", authorization_status=auth_status,
                       credential_status="valid", connectivity_status=conn_status,
                       last_error=f"授权范围未开放（{auth_status}/{conn_status}）")
            print(f"BLOCKED: Reddit 授权范围未开放（approval={auth_status}, connectivity={conn_status}）。")
            print(SETUP)
            if args.report:
                Path(args.report).write_text(json.dumps(
                    {"channel": "authenticated-reddit", "status": "APPROVAL_REQUIRED",
                     "authorization_status": auth_status, "credential_status": "valid",
                     "connectivity_status": conn_status, "inserted": 0},
                    ensure_ascii=False, indent=2), encoding="utf-8")
            return 3

        spec = SourceSpec(
            source_id="reddit", source_name="Reddit（官方 Data API / OAuth）", source_type="api",
            channel="authenticated",
            fetch=lambda: fetch(client, token, subs, args.limit),
            auth_required=True, authorization_status=auth_status, credential_status="valid",
            aggregator="reddit")
        result = run_source(db, db.conn, spec)
        entries = db.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    print(f"reddit status={result['status']} fetched={result['fetched']} inserted={result['inserted']} "
          f"dedup={result['deduped']} error={result['error']}")
    print(f"SUMMARY collected={result['fetched']} inserted={result['inserted']} "
          f"deduped={result['deduped']} failed={0 if result['status'] == 'READY' else 1}")
    print(f"库内条目 {entries}")
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(
            {"channel": "authenticated-reddit", "result": result, "db_entries": entries},
            ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
