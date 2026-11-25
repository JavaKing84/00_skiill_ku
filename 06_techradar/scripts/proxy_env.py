#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""proxy_env.py — 自动探测本机代理客户端（Karing / Clash / V2Ray 等）的可用入口。

用途
----
1. 采集器需要显式代理时，不用手工写死端口：detect_proxy() 返回第一个可用的
   `http://127.0.0.1:<port>`，探测目标为 gstatic 的 204 端点（小、快、无内容）。
2. 浏览器会话（websession）拉起 Chrome 时注入 `--proxy-server=<返回的地址>`。

优先级
------
TECH_RADAR_PROXY（显式指定） > Karing 实测端口 > 常见客户端默认端口。

边界
----
- 只探测「本机已有代理客户端」，不启动/安装任何代理软件。
- 不读取、不导出任何节点凭据或订阅信息。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PROBE_URL = os.environ.get("TECH_RADAR_PROXY_PROBE", "https://www.gstatic.com/generate_204")

# Karing 实测：3057 为 Clash 兼容控制口（需 secret），3065/3066/3067 为代理入站口
CANDIDATE_PORTS = [
    3067, 3066, 3065,          # Karing（本机实测可用）
    7897, 7890, 7891,          # Clash Verge Rev / Clash for Windows
    10809, 10808, 1080,        # v2rayN / 通用 SOCKS-HTTP
    2080, 8889,                # 其它客户端常见默认口
]


def _alive(proxy_url: str, timeout: float = 4.0) -> tuple[bool, str]:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    try:
        with opener.open(PROBE_URL, timeout=timeout) as r:
            return (r.status == 204, f"HTTP {r.status}")
    except urllib.error.HTTPError as exc:
        # 能拿到 HTTP 响应说明链路已通（403/429 属于目标站策略，不是代理不可用）
        return (exc.code < 500, f"HTTP {exc.code}")
    except Exception as exc:
        return (False, f"{type(exc).__name__}: {str(exc)[:60]}")


def probe_all(timeout: float = 4.0) -> list[dict]:
    rows = []
    for port in CANDIDATE_PORTS:
        url = f"http://127.0.0.1:{port}"
        ok, detail = _alive(url, timeout=timeout)
        rows.append({"port": port, "url": url, "ok": ok, "detail": detail})
        if ok:
            break                      # 命中即停，避免无谓占用
    return rows


def detect_proxy(timeout: float = 4.0) -> str | None:
    """返回可用代理 URL；全部不可达时返回 None（调用方应按直连继续）。"""
    explicit = (os.environ.get("TECH_RADAR_PROXY") or "").strip()
    if explicit:
        return explicit if _alive(explicit, timeout=timeout)[0] else None
    for row in probe_all(timeout=timeout):
        if row["ok"]:
            return row["url"]
    return None


def main() -> int:
    rows = probe_all()
    hit = next((r for r in rows if r["ok"]), None)
    if "--json" in sys.argv:
        print(json.dumps({"proxy": hit["url"] if hit else None, "probes": rows},
                         ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print(f"{'OK ' if r['ok'] else '-- '} {r['url']}  {r['detail']}")
        print(f"proxy={hit['url'] if hit else 'NONE'}")
    return 0 if hit else 1


if __name__ == "__main__":
    raise SystemExit(main())
