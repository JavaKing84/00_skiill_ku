#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_platform_matrix.py — 汇总 probe_site / probe_logged_in 结果，生成平台兼容矩阵。

输入：_reports/probes/*.json
输出：01_crawler/reports/platform_matrix.json + .md
矩阵只陈述**实测事实**，未测项标记 NOT_TESTED，不做推断性拔高。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IN = ROOT / "_reports" / "probes"
OUT_DIR = ROOT / "01_crawler" / "reports"

PLATFORM_OF = {
    "bili_home": ("bilibili", "page"), "bili_popular_api": ("bilibili", "api"),
    "douyin_home": ("douyin", "page"), "douyin_hot_api": ("douyin", "api"),
    "xhs_explore": ("xiaohongshu", "page"),
    "youtube_home": ("youtube", "page"),
    "wikipedia_scraping": ("generic_article", "page"),
    "reddit_api": ("reddit", "api"),
    "login_bilibili": ("bilibili", "logged_in"),
    "login_douyin": ("douyin", "logged_in"),
    "login_xiaohongshu": ("xiaohongshu", "logged_in"),
}

FIELD_MAP = {
    "ok": "ok", "http_status": "http_status", "render_layer": "render_layer",
    "structured_data": "structured_data", "media_hint": "media_hint",
    "json_ok": "json_ok", "api_code": "api_code", "verdict": "verdict",
    "challenge_detected": "challenge_detected", "error_kind": "error_kind",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", default=str(DEFAULT_IN))
    args = ap.parse_args()
    src = Path(args.in_dir)
    rows = []
    for p in sorted(src.glob("*.json")):
        if p.name in ("extract_bench.json", "github_candidates.json"):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        key = p.stem
        platform, kind = PLATFORM_OF.get(key, (key, "page"))
        row = {"probe": key, "platform": platform, "kind": kind}
        for k, v in FIELD_MAP.items():
            if k in d:
                row[v] = d[k]
        row["url"] = d.get("url")
        row["blockers"] = {k: v for k, v in (d.get("blockers") or {}).items() if v} or None
        row["note"] = d.get("note")
        rows.append(row)

    implementable = [r for r in rows if r.get("ok") and r.get("kind") in ("page", "api")]
    logged_in = [r for r in rows if r["kind"] == "logged_in"]
    payload = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "legend": "ok/status 为单次公开探测事实；render_layer 由 HTML 特征推断；logged_in 仅判定页面可见状态，未读取凭据",
        "probes_total": len(rows),
        "public_reachable": len(implementable),
        "logged_in_probes": {r["platform"]: r.get("verdict") for r in logged_in},
        "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "platform_matrix.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def conclusion(r: dict) -> str:
        if r["kind"] == "logged_in":
            return r.get("verdict") or "UNKNOWN"
        if not r.get("ok"):
            return f"BLOCKED({r.get('error_kind') or r.get('http_status')})"
        if r["kind"] == "api":
            if r.get("json_ok") is False:
                return "BLOCKED(non_json：可能需签名/风控)"
            if r.get("api_code") not in (None, 0):
                return f"BLOCKED(api_code={r.get('api_code')})"
            return "OK"
        if r.get("blockers"):
            return "BLOCKED(" + ",".join(r["blockers"].keys()) + ")"
        if r.get("render_layer") == "spa-shell":
            return "PARTIAL(需 JS 渲染)"
        return "OK"

    lines = ["# 平台兼容性矩阵（实测）", "",
             f"生成时间：{payload['generated_at']}", "",
             "> 说明：本表只记录单次公开探测事实；`spa-shell` 表示需要 JS 渲染；",
             "> `blocked` 表示触发风控/验证，**不尝试绕过**；登录态仅判定页面可见状态。", "",
             "| 平台 | 类型 | HTTP | 可达 | 渲染层 | 结构化数据 | 媒体线索 | 登录态 | 结论 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['platform']} | {r['kind']} | {r.get('http_status') or '-'} | "
                     f"{'是' if r.get('ok') else '否'} | {r.get('render_layer') or '-'} | "
                     f"{'有' if r.get('structured_data') else ('无' if r.get('structured_data') is False else '-')} | "
                     f"{'有' if r.get('media_hint') else ('无' if r.get('media_hint') is False else '-')} | "
                     f"{r.get('verdict') or '-'} | {conclusion(r)} |")
    lines += ["", "## 登录态探测（用户授权范围）", "",
              "| 平台 | 结论 | 说明 |", "|---|---|---|"]
    for r in logged_in:
        lines.append(f"| {r['platform']} | {r.get('verdict')} | "
                     f"{'检测到验证/风控，已停止' if r.get('challenge_detected') else '仅做页面可见状态判定'} |")
    (OUT_DIR / "platform_matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"rows={len(rows)} reachable={len(implementable)} -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
