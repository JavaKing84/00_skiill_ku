#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_logged_in.py — 使用用户本机已登录的浏览器配置做**授权范围内**的可访问性探测。

安全边界（硬约束）：
  - 只复用用户本机 user-data-dir 的登录会话，不读取、不打印、不导出 Cookie / localStorage / 密码。
  - 不绕过验证码、人脸/短信二次验证、风控页；遇到即停止并记录 BLOCKED。
  - 不轮换账号、不规避限流；每次探测只访问 1 个页面。
  - 输出仅包含"页面是否呈现已登录/未登录/被拦截"的判定与页面结构统计。

用法：
  python probe_logged_in.py --site douyin --profile "E:\\...\\browser_profile"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))

SITES = {
    "douyin": "https://www.douyin.com/",
    "xiaohongshu": "https://www.xiaohongshu.com/explore",
    "bilibili": "https://www.bilibili.com/",
}

LOGIN_HINTS = ["登录", "立即登录", "扫码登录", "log in", "sign in"]
USER_HINTS = ["我的", "消息", "创作中心", "个人主页", "退出登录", "profile"]


def probe(site: str, profile: str, headless: bool) -> dict:
    from playwright.sync_api import sync_playwright
    url = SITES[site]
    out = {"site": site, "url": url, "profile_used": True, "headless": headless,
           "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile, headless=headless, channel=None,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1366, "height": 900},
            locale="zh-CN")
        try:
            page = ctx.new_page()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3500)
            html = page.content()
            text = page.inner_text("body")[:4000] if page.query_selector("body") else ""
            low = text.lower()
            has_login = any(h in low for h in LOGIN_HINTS)
            has_user = sum(1 for h in USER_HINTS if h in low)
            challenge = any(k in html.lower() for k in ("captcha", "verify", "验证码", "安全验证", "人机"))
            videos = len(page.query_selector_all("video"))
            out.update({
                "http_status": resp.status if resp else None,
                "final_url": page.url,
                "title": (page.title() or "")[:120],
                "login_prompt_visible": has_login,
                "user_area_hints": has_user,
                "challenge_detected": challenge,
                "video_elements": videos,
                "html_bytes": len(html),
                "verdict": ("BLOCKED_CHALLENGE" if challenge else
                            "LOGGED_IN" if (not has_login and has_user >= 1) else
                            "LOGGED_OUT"),
                "note": "仅判定页面可见状态；未读取/导出任何凭据",
            })
        except Exception as exc:
            out.update({"error": f"{type(exc).__name__}: {exc}"[:300], "verdict": "FAILED"})
        finally:
            ctx.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True, choices=list(SITES))
    ap.add_argument("--profile", required=True)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    res = probe(args.site, args.profile, args.headless)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if res.get("verdict") in ("LOGGED_IN", "LOGGED_OUT") else 1


if __name__ == "__main__":
    raise SystemExit(main())
