"""fetch.py — 60s API 极简请求器（仅依赖 requests）。

设计原则：
  1. 只封装已验证可用的接口，不做未经验证的承诺；
  2. 主域名 60s.viki.moe 在部分地区被墙/限流，自动按顺序回退公共镜像；
  3. 超时、重试、JSON 解析失败都有明确错误信息，不静默返回空数据。

用法：
  python fetch.py --list
  python fetch.py --endpoint 60s
  python fetch.py --endpoint bili --limit 10
  python fetch.py --endpoint fanyi --param text=hello
  python fetch.py --path /v2/60s --head 100
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import requests

# 主域名优先（官方），失败后回退社区公共实例（来自官方文档「公共实例列表」）
HOSTS = [
    os.environ.get("SIXTY_S_API_BASE", "").rstrip("/"),
    "https://60s.viki.moe",
    "https://api.elysiayanyu.top",
    "https://60s.mizhoubaobei.top",
    "https://60s.okbaike.com",
]
HOSTS = [h for h in HOSTS if h]

# 仅在 2026-11-25 实测返回 200 的接口
ENDPOINTS = {
    "60s": "/v2/60s",                 # 每天 60 秒读懂世界
    "bili": "/v2/bili",               # B 站热搜
    "weibo": "/v2/weibo",             # 微博热搜
    "zhihu": "/v2/zhihu",             # 知乎热榜
    "douyin": "/v2/douyin",           # 抖音热搜
    "baidu": "/v2/baidu/hot",         # 百度热搜
    "toutiao": "/v2/toutiao",         # 今日头条
    "weather": "/v2/weather",         # 实时天气（需 city 参数，缺省北京）
    "lunar": "/v2/lunar",             # 农历 / 节假日
    "epic": "/v2/epic",               # Epic 免费游戏
    "fanyi": "/v2/fanyi",             # 翻译（需 text 参数）
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept": "application/json",
}


class FetchError(RuntimeError):
    pass


def fetch(path: str, params: dict[str, Any] | None = None, timeout: float = 10.0,
          retries: int = 1) -> tuple[dict, str]:
    """按 HOSTS 顺序尝试，返回 (json, 命中的 host)。全部失败抛 FetchError。"""
    if not path.startswith("/"):
        path = "/" + path
    errors: list[str] = []
    for host in HOSTS:
        for attempt in range(retries + 1):
            try:
                r = requests.get(host + path, params=params or {}, headers=HEADERS,
                                 timeout=timeout)
                if r.status_code != 200:
                    errors.append(f"{host}{path} -> HTTP {r.status_code}")
                    break
                data = r.json()
                code = data.get("code", data.get("status", 200))
                if code != 200:
                    errors.append(f"{host}{path} -> code {code}: {data.get('message', '')}")
                    break
                return data, host
            except requests.RequestException as exc:
                errors.append(f"{host}{path} -> {type(exc).__name__}")
                if attempt < retries:
                    time.sleep(1.0 + attempt)
                break
            except ValueError:
                errors.append(f"{host}{path} -> 响应不是合法 JSON")
                break
    raise FetchError("所有实例均不可用：\n  " + "\n  ".join(errors))


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="60s API 极简请求器")
    ap.add_argument("--endpoint", choices=sorted(ENDPOINTS), help="预设接口名")
    ap.add_argument("--path", help="自定义路径，如 /v2/60s")
    ap.add_argument("--param", action="append", default=[], metavar="K=V", help="查询参数，可重复")
    ap.add_argument("--limit", type=int, default=0, help="仅取前 N 条（列表型接口）")
    ap.add_argument("--head", type=int, default=0, help="只打印原始 JSON 的前 N 个字符")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--list", action="store_true", help="列出已支持接口")
    args = ap.parse_args()

    if args.list or (not args.endpoint and not args.path):
        print("已支持接口（实测可用）：")
        for name, path in ENDPOINTS.items():
            print(f"  {name:10s} {path}")
        print("\n示例：python fetch.py --endpoint 60s")
        return 0

    path = ENDPOINTS[args.endpoint] if args.endpoint else args.path
    params = dict(p.split("=", 1) for p in args.param if "=" in p)

    try:
        data, host = fetch(path, params, timeout=args.timeout)
    except FetchError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    if args.head:
        print(json.dumps(data, ensure_ascii=False)[: args.head])
        return 0

    if args.limit and isinstance(data.get("data"), list):
        data["data"] = data["data"][: args.limit]

    print(f"# source: {host}{path}", file=sys.stderr)
    _print_json(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
