#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""radar_query.py — 本地情报检索（SQLite 真实查询，不联网）。

能力：
  --scenario  预设场景（关键词取自 lifecycle_config.json 的 project_profiles）
  --text      自由文本（走 FTS5，不可用时自动降级 LIKE，并在输出里标明 engine）
  --since/--until   发布时间窗
  --tag       标签过滤（tags / entry_tags）
  --source    来源过滤（origin_source / aggregator / source 名）
  --related   关联检索（同 canonical_key 或显式 relations）
  --engine    auto | fts5 | like
  --init-fts  建库并回填 FTS 索引
  --mark-fetched  本次返回了正文时，把这些条目的 read_state 推进到 content_fetched（真实动作才升级）

零命中必须显式声明，不允许用记忆或泛泛综述替代。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))
from skillkit import search as sx  # noqa: E402

CONFIG = ROOT / "06_techradar" / "data" / "lifecycle_config.json"

# 内置兜底（配置缺失时使用；配置存在时以其为准，避免两处漂移）
BUILTIN_PROFILES: dict[str, list[str]] = {
    "ai-robot": ["robot", "robotics", "vla", "embodied", "manipulation", "sim2real",
                 "navigation", "simulation", "机器人", "具身", "机械臂", "多模态",
                 "quantiz", "onnx", "tensorrt", "edge inference", "multi-agent",
                 "synthetic data", "data collection"],
    "small-model": ["fine-tun", "lora", "qlora", "distill", "quantiz", "gguf", "awq",
                    "gptq", "ollama", "llama.cpp", "mlx", "sft", "dpo", "pretrain",
                    "tokenizer", "dataset", "微调", "量化", "蒸馏", "小模型", "benchmark"],
    "douyin-growth": ["ffmpeg", "subtitle", "tts", "voice clone", "remotion", "automation",
                      "视频", "剪辑", "字幕", "配音", "素材", "自动化", "运营", "封面"],
    "ai-agent": ["agent", "multi-agent", "mcp", "workflow", "tool-use", "rag", "智能体"],
}


TECH_HINTS = re.compile(
    r"bypass|stealth|headless|impersonate|curl[_-]?cffi|tls|fingerprint|403|401|429|"
    r"captcha|cloudflare|anti[-_ ]?bot|schtasks|s4u|system account|0x[0-9a-f]{8}|"
    r"permission|access is denied|playwright|selenium|puppeteer|traceback|exception|"
    r"反爬|风控|权限|提权|报错|异常|计划任务|无头|指纹",
    re.I)

# 技术排障优先级：知识库 > 代码/问答 > 技术社区 > Release
TECH_SOURCE_PRIORITY = [
    "knowledge_base", "github_issues", "stackoverflow",
    "reddit_tech", "reddit", "folo",
    "github_releases", "github_search", "topic_search", "rss_official", "arxiv",
]
# 新闻/聚合类来源在技术意图下不参与填充
TECH_EXCLUDE = {
    "sec_rss", "sec_restricted", "github_advisories", "cisa_kev",
    "radar_zcl", "radar.zichuanlan.top", "hn_frontpage",
}


def detect_intent(text: str, explicit: str = "auto") -> str:
    if explicit in ("tech", "news"):
        return explicit
    return "tech" if text and TECH_HINTS.search(text) else "news"


def _tech_rows(conn, *, text, since, until, tags, limit, engine, order):
    """按来源优先级逐源查询并合并，保证知识库/Issues/SO 排在新闻之前。"""
    rows: list[dict] = []
    seen: set[int] = set()
    engines: list[str] = []
    for src in TECH_SOURCE_PRIORITY:
        if len(rows) >= limit:
            break
        r = sx.query_entries(conn, text=text, since=since, until=until, tags=tags,
                             sources=[src], limit=limit, engine=engine, order=order)
        engines.append(r["engine"])
        for row in r["rows"]:
            eid = row["entry_id"]
            if eid in seen:
                continue
            seen.add(eid)
            rows.append(row)
            if len(rows) >= limit:
                break
    if len(rows) < limit and text:
        r = sx.query_entries(conn, text=text, since=since, until=until, tags=tags,
                             limit=limit * 4, engine=engine, order=order)
        engines.append(r["engine"])
        for row in r["rows"]:
            if len(rows) >= limit:
                break
            src = row.get("source_name") or ""
            if src in TECH_EXCLUDE or row["entry_id"] in seen:
                continue
            seen.add(row["entry_id"])
            rows.append(row)
    used = "fts5" if "fts5" in engines else (engines[0] if engines else "none")
    return rows, used


def load_profiles() -> dict[str, list[str]]:
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        profiles = cfg.get("project_profiles") or {}
        if profiles:
            merged = {k: list(v) for k, v in BUILTIN_PROFILES.items()}
            for k, v in profiles.items():
                merged[k] = list(v)
            return merged
    except (OSError, json.JSONDecodeError):
        pass
    return {k: list(v) for k, v in BUILTIN_PROFILES.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--scenario", default="", help="预设场景：ai-robot / small-model / douyin-growth / ai-agent")
    ap.add_argument("--text", default="", help="自由文本检索")
    ap.add_argument("--keywords", default="", help="逗号分隔关键词（与 --text 等价）")
    ap.add_argument("--since", default="", help="起始发布时间，含，如 2026-11-01")
    ap.add_argument("--until", default="", help="截止发布时间，含")
    ap.add_argument("--tag", default="", help="标签过滤，逗号分隔")
    ap.add_argument("--source", default="", help="来源过滤，逗号分隔")
    ap.add_argument("--related", type=int, default=None, help="与指定 entry_id 关联的条目")
    ap.add_argument("--engine", choices=["auto", "fts5", "like"], default="auto")
    ap.add_argument("--intent", choices=["auto", "tech", "news"], default="auto",
                    help="技术意图过滤：tech 时优先知识库/Issues/SO/技术社区，过滤安全新闻")
    ap.add_argument("--order", choices=["published_desc", "cross_source_desc", "oldest"], default="published_desc")
    ap.add_argument("--init-fts", action="store_true", help="创建并回填 FTS 索引")
    ap.add_argument("--mark-fetched", action="store_true", help="返回正文时推进 read_state 到 content_fetched")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    profiles = load_profiles()
    text = args.text or (args.keywords.replace(",", " ") if args.keywords else "")
    scenario = args.scenario
    label = "自定义检索"
    if scenario:
        if scenario not in profiles:
            print(f"FAIL: 未知场景 {scenario}，可选：{sorted(profiles)}")
            return 2
        text = " ".join(profiles[scenario])
        label = f"场景检索 · {scenario}"

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"FAIL: 情报库不存在 {db_path}")
        return 2

    conn = sqlite3.connect(f"file:{db_path}?mode=rw", uri=True)
    conn.row_factory = sqlite3.Row

    fts_state = None
    if args.init_fts:
        n = sx.rebuild_fts(conn)
        fts_state = f"fts_rebuilt({n})"
        print(f"FTS 索引已建立并回填 {n} 条")
    elif args.engine in ("auto", "fts5"):
        fts_state = "fts_available" if sx.ensure_fts(conn) else "fts_unavailable"

    if not text and not args.since and not args.until and not args.tag and not args.source and args.related is None:
        print("FAIL: 至少需要一个检索条件（--text/--scenario/--since/--tag/--source/--related）")
        return 2

    intent = detect_intent(text, args.intent)
    tag_list = [t for t in args.tag.split(",") if t] or None
    source_list = [s for s in args.source.split(",") if s] or None
    if intent == "tech" and not source_list and args.related is None:
        rows, used_engine = _tech_rows(
            conn, text=text or None, since=args.since or None, until=args.until or None,
            tags=tag_list, limit=args.limit, engine=args.engine, order=args.order)
        result = {"engine": used_engine, "rows": rows, "filters": {
            "text": text or None, "since": args.since or None, "until": args.until or None,
            "tags": tag_list, "sources": None, "related_to": None, "intent": intent}}
    else:
        result = sx.query_entries(
            conn, text=text or None,
            since=args.since or None, until=args.until or None,
            tags=tag_list, sources=source_list,
            related_to=args.related, limit=args.limit, engine=args.engine, order=args.order,
        )
        result["filters"]["intent"] = intent
    rows = result["rows"]

    if args.mark_fetched and rows:
        from skillkit.inteldb import IntelDB
        fetched = 0
        with IntelDB(db_path) as db:
            for r in rows:
                if r.get("extra_json") and '"content"' in r["extra_json"]:
                    if db.mark_read_state(r["url"], "content_fetched") == "content_fetched":
                        fetched += 1
        result["marked_content_fetched"] = fetched

    payload = {
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "scenario": scenario or "custom",
        "label": label,
        "intent": intent,
        "engine": result["engine"],
        "fts_state": fts_state,
        "filters": result["filters"],
        "hit_count": len(rows),
        "zero_hit": len(rows) == 0,
        "hits": rows,
        "disclaimer": "命中为本地 SQLite 真实查询结果；是否采用需人工核验原链接；cross_source_count>1 表示跨源复现",
    }
    print(f"{label}: hits={len(rows)} engine={result['engine']} fts={fts_state}")
    for h in rows[:12]:
        src = h["aggregator"] or h["source_name"]
        origin = f" <- {h['origin_source']}" if h["origin_source"] else ""
        tags = f" [{','.join(h.get('tags') or [])}]" if h.get("tags") else ""
        print(f"  [{h.get('corrected_category') or h.get('category')}] {h['title'][:44]} "
              f"| {src}{origin}{tags} | x{h['cross_source_count']} | {h['published_at']}")
    if not rows:
        print("ZERO-HIT：本地库当前无匹配；不得用记忆或泛泛综述替代，应扩大采集或调整关键词。")

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"-> {p}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
