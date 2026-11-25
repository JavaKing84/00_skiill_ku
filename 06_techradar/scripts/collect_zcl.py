#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_zcl.py — 资源雷达（radar.zichuanlan.top）二级聚合源采集器。

仅使用站点公开只读接口（实测 2026-11-17）：
  GET /health            运行状态
  GET /api/items         列表（实测支持 kind/category/limit/offset；q/source_id 服务端不过滤，改客户端筛）
  GET /api/items/{id}    详情（content 字段为正文，部分条目为空）
管理类接口返回 401，本脚本不触碰、不尝试鉴权。

溯源策略：
  - 聚合渠道统一登记为 sources 行 radar.zichuanlan.top（kind=aggregator）
  - 条目的上游源（如 tg-cn-deals/rss-ithome）写入 entries.origin_source，绝不冒充独立新源
  - 原始链接写入 entries.url，canonical_key 支持与直采 GitHub/HN 条目跨源关联
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
from skillkit.inteldb import IntelDB  # noqa: E402
from skillkit.policy import CrawlPolicy  # noqa: E402

BASE = "https://radar.zichuanlan.top"
AGGREGATOR = "radar.zichuanlan.top"
TECH_KINDS = ("opensource", "info", "news")
TECH_CATEGORIES = ("ai", "dev", "tech", "opensource", "security", "design", "cloud", "software")
HEADERS = {"User-Agent": "skillkit-techradar/1.0 (+local research; read-only; low frequency)",
           "Accept": "application/json"}


class ZclClient:
    def __init__(self, policy: CrawlPolicy):
        self.policy = policy
        self.session = requests.Session()
        self.session.trust_env = False  # 不受系统代理环境变量干扰
        self._last_request = 0.0

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_request
        if gap < self.policy.min_interval_seconds:
            time.sleep(self.policy.min_interval_seconds - gap)
        self._last_request = time.monotonic()

    def get(self, path: str) -> requests.Response:
        url = BASE + path
        last_err = None
        for attempt in range(self.policy.max_retries + 1):
            self._throttle()
            try:
                r = self.session.get(url, headers=HEADERS, timeout=self.policy.timeout_seconds)
                if r.status_code >= 500 and attempt < self.policy.max_retries:
                    last_err = f"HTTP {r.status_code}"
                    time.sleep(self.policy.backoff(attempt + 1))
                    continue
                return r
            except requests.RequestException as exc:
                last_err = type(exc).__name__
                if attempt < self.policy.max_retries:
                    time.sleep(self.policy.backoff(attempt + 1))
                    continue
                raise
        raise RuntimeError(f"GET {path} failed after retries: {last_err}")

    def health(self) -> dict:
        return self.get("/health").json()

    def list_items(self, kind: str | None, category: str | None,
                   limit: int, offset: int) -> dict:
        params = [f"limit={limit}", f"offset={offset}"]
        if kind:
            params.append(f"kind={kind}")
        if category:
            params.append(f"category={category}")
        return self.get("/api/items?" + "&".join(params)).json()

    def item_detail(self, item_id: int) -> dict:
        return self.get(f"/api/items/{item_id}").json()


def map_item(item: dict, detail_content: str | None) -> dict:
    ai = item.get("ai") or {}
    metrics = {
        "score": item.get("score"),
        "ai_quality": item.get("ai_quality"),
        "dup_count": item.get("dupCount"),
        "obtain": item.get("obtain"),
        "is_free": item.get("is_free"),
        "price": item.get("price"),
        "tags": item.get("tags"),
        "ai_keep": ai.get("keep"),
        "ai_reason": ai.get("reason"),
    }
    extra = {
        "external_id": item.get("external_id"),
        "image_url": item.get("image_url"),
        "expires_at": item.get("expires_at"),
        "title_key": item.get("title_key"),
        "url_key_upstream": item.get("url_key"),
        "matched": item.get("matched"),
        "detail_fetched": detail_content is not None,
    }
    return {
        "external_key": f"zcl:{item['id']}",
        "aggregator": AGGREGATOR,
        "origin_source": item.get("source_id"),
        "url": item.get("url"),
        "title": item.get("title"),
        "author": item.get("author"),
        "published_at": item.get("published_at"),
        "summary": item.get("summary"),
        "content": detail_content,
        "category": item.get("category"),
        "ai_category": ai.get("category") or item.get("category"),
        "link_status": item.get("status") or "unknown",
        "first_seen_at": item.get("first_seen_at"),
        "last_seen_at": item.get("last_seen_at"),
        "metrics": metrics,
        "extra": extra,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--max-items", type=int, default=60, help="本次最多入库条目数（分页总量上限）")
    ap.add_argument("--page-size", type=int, default=40)
    ap.add_argument("--detail-limit", type=int, default=10, help="最多补拉多少条详情正文")
    ap.add_argument("--kinds", default=",".join(TECH_KINDS))
    ap.add_argument("--categories", default=",".join(TECH_CATEGORIES))
    ap.add_argument("--report", default="", help="可选：把本次运行统计写为 JSON")
    args = ap.parse_args()

    policy = CrawlPolicy(min_interval_seconds=1.6, timeout_seconds=25)
    client = ZclClient(policy)

    health = client.health()
    if not health.get("ok"):
        print(f"FAIL health: {health}")
        return 2

    # 服务端 kind 过滤有效；多分类用客户端合并去重（同一 external id 只处理一次）
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    wanted_cats = {c.strip() for c in args.categories.split(",") if c.strip()}
    picked: dict[int, dict] = {}
    page_offsets = list(range(0, args.max_items, args.page_size))
    for kind in kinds:
        for offset in page_offsets:
            if len(picked) >= args.max_items:
                break
            payload = client.list_items(kind, None, args.page_size, offset)
            batch = payload.get("items", [])
            if not batch:
                break
            for it in batch:
                if len(picked) >= args.max_items:
                    break
                if it["id"] in picked:
                    continue
                if it.get("category") in wanted_cats or kind == it.get("kind"):
                    picked[it["id"]] = it
            if offset + args.page_size >= payload.get("total", 0):
                break

    # 详情补正文（限量，避免高频请求）
    detail_contents: dict[int, str | None] = {}
    for iid in list(picked)[: args.detail_limit]:
        try:
            detail = client.item_detail(iid)
            detail_contents[iid] = detail.get("content")
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            detail_contents[iid] = None
            print(f"WARN detail {iid}: {type(exc).__name__}")

    inserted = updated = with_content = 0
    origin_sources: dict[str, int] = {}
    with IntelDB(args.db) as db:
        for iid, item in picked.items():
            rec = map_item(item, detail_contents.get(iid))
            verdict = db.upsert_aggregated_entry(**rec)
            inserted += verdict == "inserted"
            updated += verdict == "updated"
            if rec["content"]:
                with_content += 1
            origin_sources[rec["origin_source"]] = origin_sources.get(rec["origin_source"], 0) + 1
        stats = db.stats()

    summary = {
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "health": health,
        "fetched_picked": len(picked),
        "inserted": inserted,
        "updated": updated,
        "detail_with_content": with_content,
        "detail_requested": min(len(picked), args.detail_limit),
        "origin_source_distribution": origin_sources,
        "db_stats": stats,
        "note": "源为二级聚合器；origin_source 保留上游渠道，canonical_key 用于跨源关联",
    }
    line = (f"ZCL picked={len(picked)} inserted={inserted} updated={updated} "
            f"content={with_content}/{summary['detail_requested']} origins={len(origin_sources)}")
    print(line)
    if args.report:
        p = Path(args.report)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"-> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
