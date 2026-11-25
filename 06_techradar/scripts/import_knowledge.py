#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""import_knowledge.py — 把实战排障知识直接写入 TechRadar 情报库。

来源：2026-11-24 对 Reddit 403 / 浏览器生命周期 / 计划任务权限的实测复盘。
写入后可被 radar_query.py 精确检索（title/summary/content 均进 FTS5）。

用法：
  python import_knowledge.py --db ...\techradar.db
  python import_knowledge.py --db ...\techradar.db --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))

from skillkit.inteldb import IntelDB  # noqa: E402

NOW = datetime.now().isoformat(timespec="seconds")

ENTRIES = [
    {
        "title": "Playwright/Chrome 反爬实战：--headless=new 易被识别，改用 --window-position=-32000,-32000 离屏真实窗口",
        "url": "https://playwright.dev/python/docs/browsers",
        "summary": ("Reddit 对 headless 特征敏感：同一登录态下 --headless=new 返回 403，"
                    "offscreen 真实窗口返回 200。结论：优先离屏真实窗口；无桌面环境才用 headless，并接受失败率。"),
        "content": """# 结论
同一 Chrome 配置目录、同一登录 Cookie：
- `--headless=new`：Reddit 返回 403（blocked by network security）
- `--window-position=-32000,-32000 --window-size=1440,900`：返回 200，DOM 正常

# 启动参数（Windows）
```python
args = [
    chrome, "--remote-debugging-port=9333", "--remote-allow-origins=*",
    f"--user-data-dir={PROFILE_DIR}", "--no-first-run", "--no-default-browser-check",
    "--window-position=-32000,-32000", "--window-size=1440,900",
]
if mode == "headless":
    args += ["--headless=new", "--disable-gpu"]
```

# 适用边界
- 站点只检测 `navigator.webdriver` 时，headless 也能过；
- 站点检测 UA-CH / GPU / 窗口尺寸 / 渲染特征时，headless 会被识别；
- 无桌面会话（Windows 服务 / SYSTEM）只能 headless，需接受被拦截的可能。

# 验证方法
```python
resp = page.goto("https://www.reddit.com/r/LocalLLaMA/new/", wait_until="domcontentloaded")
print(resp.status, "blocked" in page.inner_text("body").lower())
```
""",
        "tags": ["anti-bot", "troubleshooting", "code-snippet", "playwright"],
        "category": "troubleshooting",
    },
    {
        "title": "curl_cffi TLS 指纹伪装：impersonate=chrome 的正确用法与失效边界（IP 被风控时无效）",
        "url": "https://github.com/lexiforest/curl_cffi",
        "summary": ("curl_cffi 用 impersonate 参数伪造 Chrome 的 TLS/HTTP2 指纹，可解决部分 403；"
                    "但若站点按出口 IP 风控（Reddit 即如此），指纹伪装无效，仍需换出口或真实浏览器。"),
        "content": """# 基本用法
```python
from curl_cffi import requests as creq

r = creq.get(
    "https://example.com/api",
    impersonate="chrome",          # 可选 chrome110 / chrome120 / safari 等
    timeout=25,
    headers={"Accept-Language": "en-US,en;q=0.9"},
)
print(r.status_code, r.text[:200])
```

# 带代理与 Cookie
```python
s = creq.Session(impersonate="chrome")
r = s.get(url, proxies={"http": "http://127.0.0.1:3067",
                        "https": "http://127.0.0.1:3067"},
          cookies={"session": "..."} , timeout=25)
```

# 实测结论（Reddit）
- 直连：`curl (28) Failed to connect ... after 21s`（DNS/网络层不可达）
- 走本机代理：403，190KB “blocked by network security”
- 带登录 Cookie：仍 403 → 说明不是指纹问题，而是出口 IP 被风控

# 判断顺序
1. 403 页面是否包含 Cloudflare/风控文案；
2. 换 UA/指纹是否变化；
3. 换出口 IP 是否变化；
4. 都不变 → 用真实浏览器 + 登录态。
""",
        "tags": ["anti-bot", "code-snippet", "curl-cffi", "troubleshooting"],
        "category": "troubleshooting",
    },
    {
        "title": "Reddit 反爬判别：JSON 接口 403，改用真实浏览器 DOM（shreddit-post）抓取",
        "url": "https://www.reddit.com/r/webscraping/",
        "summary": ("Reddit 的 /new.json 对数据中心 IP 返回 403，但真实浏览器打开 /r/<sub>/new/ 可正常渲染。"
                    "用 shreddit-post 属性提取标题/链接/时间/分数，8–15 秒随机间隔。"),
        "content": """# 判别
- `GET /r/<sub>/new.json` → 403（blocked by network security）
- `GET /r/<sub>/new/`（真实浏览器 + 登录 Cookie）→ 200
- `/r/<sub>/.rss` → 404（Reddit 已下线该 feed）

# DOM 提取（Playwright）
```python
JS = '''() => Array.from(document.querySelectorAll('shreddit-post')).map(el => ({
  title: el.getAttribute('post-title'),
  permalink: el.getAttribute('permalink'),
  created: el.getAttribute('created-timestamp'),
  author: el.getAttribute('author'),
  score: el.getAttribute('score'),
  comments: el.getAttribute('comment-count')
}))'''
posts = page.evaluate(JS)
page.evaluate("window.scrollBy(0, 2600)")  # 触发懒加载
```

# 节奏
- 每个 subreddit 间隔 8–15 秒；
- 先试 JSON，403 再回退 DOM；
- headless 会被识别，使用 offscreen 真实窗口。

# 入库字段
url = "https://www.reddit.com" + permalink
external_key = f"reddit:{post_id}"
tags = ["reddit", subreddit]
""",
        "tags": ["anti-bot", "troubleshooting", "code-snippet", "reddit"],
        "category": "troubleshooting",
    },
    {
        "title": "Windows 计划任务 SYSTEM/S4U 提权：解决 0x80070005 Access is denied（schtasks 无论用户是否登录都运行）",
        "url": "https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-start-page",
        "summary": ("普通权限注册 SYSTEM/S4U 计划任务会返回 Access is denied (0x80070005)。"
                    "需管理员 PowerShell 执行 Set-ScheduledTask -Principal；并设置 WakeToRun 唤醒计算机。"),
        "content": """# 现象
```
Register-ScheduledTask : Access is denied.
HRESULT 0x80070005
```
SYSTEM（ServiceAccount）与 S4U 两种 LogonType 都会被拒，因为需要管理员权限。

# 管理员 PowerShell：切换为 SYSTEM
```powershell
$p = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Set-ScheduledTask -TaskName 'TechRadar_Daily' -Principal $p
```

# 管理员 PowerShell：S4U（当前用户，无需密码，登录与否都运行）
```powershell
$p = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\\$env:USERNAME" `
       -LogonType S4U -RunLevel Limited
Set-ScheduledTask -TaskName 'TechRadar_Daily' -Principal $p
```

# 配套设置
```powershell
$t = Get-ScheduledTask -TaskName 'TechRadar_Daily'
$t.Settings.WakeToRun = $true
$t.Settings.StartWhenAvailable = $true
$t.Settings.DisallowStartIfOnBatteries = $false
$t.Settings.StopIfGoingOnBatteries = $false
Set-ScheduledTask -TaskName 'TechRadar_Daily' -Settings $t.Settings
```

# 注意
- SYSTEM/S4U 运行在 session 0，没有桌面；浏览器自动化需改用 headless；
- `Last Result=0x800710E0`（The operator or administrator has refused the request）
  通常是电池策略或登录会话限制，不是权限不足。
""",
        "tags": ["windows-permission", "troubleshooting", "code-snippet"],
        "category": "troubleshooting",
    },
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    stats = {"inserted": 0, "duplicate": 0, "ids": []}
    if args.dry_run:
        print(json.dumps({"dry_run": True, "count": len(ENTRIES),
                          "titles": [e["title"] for e in ENTRIES]},
                         ensure_ascii=False, indent=1))
        return 0

    with IntelDB(Path(args.db)) as db:
        for e in ENTRIES:
            verdict = db.add_entry(
                source_name="knowledge_base", source_kind="kb",
                url=e["url"], title=e["title"], summary=e["summary"],
                published_at=NOW, author="TechRadar 实战复盘",
                category=e["category"], tags=e["tags"],
                origin_source="knowledge_base",
                extra={"content": e["content"], "code_snippets": True,
                       "confidence": "verified", "verified_at": NOW,
                       "evidence": "2026-11-24 Reddit/Playwright/schtasks 实测"},
            )
            stats[verdict] = stats.get(verdict, 0) + 1
            if verdict == "inserted":
                row = db.conn.execute("SELECT entry_id FROM entries WHERE url=? AND title=?",
                                      (e["url"], e["title"])).fetchone()
                if row:
                    stats["ids"].append(row[0])
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
