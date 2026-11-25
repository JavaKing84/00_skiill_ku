#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""healthcheck.py — TechRadar 数据源健康检查（Phase 3.1）。

检查两层：
  1) 本地配置层：~/.trae-cn/mcp.json 是否存在、各服务器凭证字段是否已填（只看是否为空，不打印值）。
  2) 公开网络层：无需登录的 HN/GitHub API 是否可达（低频、单次请求）。
Folo/Reddit 的 MCP 级真实调用结果由 Trae 会话实测，经 --mcp-folo/--mcp-reddit 参数并入报告。
输出 JSON + Markdown 状态条，绝不输出密钥内容。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

DEFAULT_MCP = Path.home() / ".trae-cn" / "mcp.json"
TIMEOUT = 15


def check_config(path: Path) -> dict:
    result = {"mcp_json_exists": path.exists(), "servers": {}}
    if not path.exists():
        return result
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result["parse_error"] = str(exc)
        return result
    for name, conf in cfg.get("mcpServers", {}).items():
        entry = {"transport": "http" if conf.get("url") else "stdio", "credential_fields": [], "configured": []}
        for hk in (conf.get("headers") or {}):
            entry["credential_fields"].append(f"headers.{hk}")
            if conf["headers"].get(hk):
                entry["configured"].append(f"headers.{hk}")
        for ek, ev in (conf.get("env") or {}).items():
            entry["credential_fields"].append(f"env.{ek}")
            if ev:
                entry["configured"].append(f"env.{ek}")
        entry["complete"] = sorted(entry["configured"]) == sorted(entry["credential_fields"])
        result["servers"][name] = entry
    return result


def check_endpoint(name: str, url: str) -> dict:
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "skillkit-healthcheck/1.0"})
        return {"name": name, "url": url, "http_status": r.status_code,
                "ok": r.status_code == 200}
    except requests.RequestException as exc:
        return {"name": name, "url": url, "http_status": None,
                "ok": False, "error": type(exc).__name__}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mcp-config", default=str(DEFAULT_MCP))
    ap.add_argument("--mcp-folo", choices=["ok", "auth_required", "unavailable", "untested"], default="untested")
    ap.add_argument("--mcp-reddit", choices=["ok", "auth_required", "unavailable", "untested"], default="untested")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    zcl = check_endpoint("zcl-radar-health", "https://radar.zichuanlan.top/health")
    zcl_items = check_endpoint("zcl-radar-items", "https://radar.zichuanlan.top/api/items?limit=1")
    report = {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "config_layer": check_config(Path(args.mcp_config)),
        "mcp_session_evidence": {"folo": args.mcp_folo, "reddit": args.mcp_reddit},
        "public_endpoints": [
            check_endpoint("hackernews-algolia", "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=1"),
            check_endpoint("github-api", "https://api.github.com/rate_limit"),
            zcl,
            zcl_items,
        ],
        "aggregator_sources": {
            "radar.zichuanlan.top": {
                "health_ok": bool(zcl.get("ok")),
                "items_api_ok": bool(zcl_items.get("ok")),
                "auth_required_for_admin": True,  # 管理接口 401，采集仅用公开只读接口
            }
        },
    }
    folo_state = "auth_required" if args.mcp_folo != "ok" else "ok"
    reddit_state = "auth_required" if args.mcp_reddit != "ok" else "ok"
    report["summary_line"] = (
        f"Folo: {folo_state} | Reddit: {reddit_state} | "
        f"HN: {report['public_endpoints'][0]['ok']} | GitHub: {report['public_endpoints'][1]['ok']} | "
        f"ZCL: {zcl.get('ok') and zcl_items.get('ok')}"
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report["summary_line"])
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
