#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_site.py — 网站公开可访问性与数据结构探测（P0 情报层的可执行实现）。

只做合法公开探测：单次 GET，不登录、不绕验证码、不构造签名、不高频。
输出结构化画像卡，回答四个问题：
  1) 未登录能否访问（状态码 / 最终 URL / 是否被拦）
  2) 页面是 SSR 还是 JS 空壳（渲染层判定）
  3) 有没有公开结构化数据（JSON-LD / __NEXT_DATA__ / 内嵌 JSON / og 标签）
  4) 有没有公开媒体资源线索（<video> / og:video / m3u8 字样）

用法：
  python probe_site.py --url https://www.bilibili.com/ --out reports/probe_bili.json
  python probe_site.py --url https://api.bilibili.com/x/web-interface/popular?ps=3 --api
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))

from skillkit.http import FetchError, HttpClient  # noqa: E402
from skillkit.policy import CrawlPolicy  # noqa: E402

SSR_MARKERS = {
    "__NEXT_DATA__": r'id="__NEXT_DATA__"',
    "INITIAL_STATE": r"__INITIAL_STATE__",
    "NUXT": r"__NUXT__",
    "NUXT_DATA": r"__NUXT_DATA__",
    "PRELOADED_STATE": r"__PRELOADED_STATE__",
    "ld+json": r'application/ld\+json',
    "og:title": r'property="og:title"',
    "og:video": r'property="og:video',
    "video_tag": r"<video",
    "m3u8": r"\.m3u8",
}
BLOCK_MARKERS = {
    "captcha": r"captcha|验证码|人机验证|安全验证|滑动验证",
    "login_wall": r"请登录后|登录后查看|login required|sign in to continue",
    "access_denied": r"访问受限|无权访问|403 forbidden|access denied",
    "risk_control": r"异常流量|风控|操作过于频繁",
}


def classify_page(html: str) -> dict:
    markers = {k: bool(re.search(v, html, re.I)) for k, v in SSR_MARKERS.items()}
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:160]
    visible = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    visible = re.sub(r"<[^>]+>", " ", visible)
    text = re.sub(r"\s+", " ", visible).strip()
    text_len = len(text)
    # 阻断词只在标题 + 正文前 6000 字符里判定，避免正文出现 "verify/权限" 等词误伤
    scope = (title + " " + text[:6000]).lower()
    blockers = {k: bool(re.search(v, scope, re.I)) for k, v in BLOCK_MARKERS.items()}
    scripts = len(re.findall(r"<script", html, re.I))
    return {
        "title": title,
        "html_bytes": len(html.encode("utf-8", errors="ignore")),
        "visible_text_chars": text_len,
        "script_tags": scripts,
        "ssr_markers": markers,
        "blockers": blockers,
        "render_layer": ("ssr" if text_len > 1500 and not markers.get("NUXT") else
                         "spa-shell" if markers.get("__NEXT_DATA__") or markers.get("INITIAL_STATE")
                         or markers.get("NUXT") else
                         "unknown"),
        "structured_data": bool(markers.get("ld+json") or markers.get("__NEXT_DATA__")
                                or markers.get("INITIAL_STATE")),
        "media_hint": bool(markers.get("video_tag") or markers.get("og:video")
                           or markers.get("m3u8")),
    }


def probe(url: str, api: bool = False) -> dict:
    policy = CrawlPolicy(timeout_seconds=25, max_retries=1, min_interval_seconds=2.0)
    client = HttpClient(policy)
    started = time.monotonic()
    out = {"url": url, "kind": "api" if api else "page", "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        r = client.get(url)
    except FetchError as exc:
        out.update({"ok": False, "error": str(exc), "error_kind": exc.kind,
                    "http_status": exc.status, "elapsed_ms": int((time.monotonic() - started) * 1000)})
        return out
    elapsed = int((time.monotonic() - started) * 1000)
    ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    out.update({"ok": 200 <= r.status_code < 300, "http_status": r.status_code,
                "final_url": r.url, "content_type": ctype, "bytes": len(r.content),
                "elapsed_ms": elapsed})
    if api or "json" in ctype:
        try:
            data = r.json()
            out["json_ok"] = True
            if isinstance(data, dict):
                out["json_keys"] = list(data.keys())[:20]
                code = data.get("code")
                if code is not None:
                    out["api_code"] = code
                out["item_count"] = (len(data.get("data", {}).get("list", []))
                                     if isinstance(data.get("data"), dict)
                                     and isinstance(data["data"].get("list"), list) else None)
            elif isinstance(data, list):
                out["json_keys"] = None
                out["item_count"] = len(data)
        except ValueError:
            out["json_ok"] = False
    else:
        html = r.text[:400000]
        out.update(classify_page(html))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--api", action="store_true", help="按 JSON 接口探测")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    res = probe(args.url, api=args.api)
    print(json.dumps(res, ensure_ascii=False, indent=2)[:1800])
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"-> {p}")
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
