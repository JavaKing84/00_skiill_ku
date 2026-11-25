#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""websession.py — 用浏览器登录态采集 Folo / Reddit（方案 A/B）。

原理
----
Chrome 136+ 禁止对「默认用户目录」开启远程调试，因此这里使用复制到
`D:\\00_skiill_ku\\_browser_profile` 的独立配置目录（含 Cookies / Local State），
以 `--remote-debugging-port=9333` 启动；再通过 Playwright `connect_over_cdp`
复用其中的登录 Cookie 访问：

  Folo   : https://api.folo.is/subscriptions?view=0  →  POST /entries（同源 fetch）
  Reddit : https://www.reddit.com/r/<sub>/new.json

安全与边界
----------
- 只读取本机浏览器已有登录态，不输入账号密码、不绕过验证码。
- Cookie 只在本进程内存中使用，不写入日志/数据库/报告。
- Reddit 返回 403 时抛 WebSessionBlocked，由调用方标记 BLOCKED，不伪造数据。
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))

from skillkit.pipeline import Record  # noqa: E402

try:
    from proxy_env import detect_proxy  # noqa: E402
except ImportError:                                   # 作为包被导入时的兜底
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from proxy_env import detect_proxy  # noqa: E402

CDP_PORT = int(os.environ.get("TECH_RADAR_CDP_PORT", "9333"))
CDP_URL = os.environ.get("TECH_RADAR_CDP", f"http://127.0.0.1:{CDP_PORT}")
PROFILE_DIR = Path(os.environ.get("TECH_RADAR_BROWSER_PROFILE", str(ROOT / "_browser_profile")))
BROWSER_MODE = os.environ.get("TECH_RADAR_BROWSER_MODE", "offscreen").lower()  # offscreen | headless
AUTOCLOSE = os.environ.get("TECH_RADAR_BROWSER_AUTOCLOSE", "1") != "0"
PID_FILE = ROOT / "06_techradar" / "data" / "browser_session.json"
CHROME_CANDIDATES = [
    r"C:\Users\26808\AppData\Local\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


class WebSessionError(RuntimeError):
    """浏览器会话不可用（未启动 / 无 Cookie / 页面异常）。"""


class WebSessionBlocked(WebSessionError):
    """站点明确拒绝（403/风控），属于不可绕过的阻塞。"""


def _cdp_ok(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(CDP_URL + "/json/version", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _chrome_exe() -> str | None:
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _profile_pids() -> list[int]:
    """只匹配使用本项目独立配置目录的 Chrome，绝不碰用户日常 Chrome。"""
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        "Where-Object { $_.CommandLine -like '*_browser_profile*' } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=20)
        return [int(x) for x in (out.stdout or "").split() if x.strip().isdigit()]
    except Exception:
        return []


def _kill_pids(pids: list[int]) -> None:
    """只终止调用方精确匹配到的 PID 列表。

    红线（爬虫库 SKILL.md C11）：禁止 `taskkill /F /IM chrome.exe`。
    用户可能同时开着投递/办公用的 Chrome 调试会话，全局杀进程会直接毁掉其工作状态；
    这里的 pids 一律来自 `_profile_pids()` 的 `*_browser_profile*` 命令行匹配。
    """
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=20)
        except Exception:
            pass


def _write_pid_file(pids: list[int], proxy: str | None = None) -> None:
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(json.dumps({"pids": pids, "mode": BROWSER_MODE,
                                        "proxy": proxy,
                                        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}),
                            encoding="utf-8")
    except Exception:
        pass


def ensure_browser(wait_seconds: int = 40) -> bool:
    """确保调试端口可用。返回 True 表示本次由本进程拉起（用于采集后自动关闭）。

    残留处理：端口无响应时，先按独立配置目录匹配并杀掉残留 Chrome，再重新拉起。
    """
    if _cdp_ok():
        return False
    stale = _profile_pids()
    if stale:
        _kill_pids(stale)
        time.sleep(2)
    chrome = _chrome_exe()
    if not chrome:
        raise WebSessionError("未找到 chrome.exe，无法启动浏览器会话")
    if not (PROFILE_DIR / "Default" / "Network" / "Cookies").exists():
        raise WebSessionError(
            f"缺少登录态配置目录 {PROFILE_DIR}；请先执行 tasks/refresh_browser_profile.ps1")
    args = [
        chrome, f"--remote-debugging-port={CDP_PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={PROFILE_DIR}", "--no-first-run", "--no-default-browser-check",
        "--disable-background-networking", "--disable-sync",
    ]
    proxy = detect_proxy()
    if proxy:
        # 强制本会话走本机代理客户端；系统代理未开时也能生效（Karing 默认不开系统代理）
        args.append(f"--proxy-server={proxy}")
    else:
        print("[websession] 未检测到可用本地代理，按直连启动（站点按 IP 拦截时会 403）",
              file=sys.stderr)
    if BROWSER_MODE == "headless":
        args += ["--headless=new", "--disable-gpu", "--window-size=1440,900"]
    else:
        args += ["--window-position=-32000,-32000", "--window-size=1440,900"]
    args.append("about:blank")
    subprocess.Popen(args, creationflags=DETACHED, close_fds=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(wait_seconds):
        time.sleep(1)
        if _cdp_ok():
            _write_pid_file(_profile_pids(), proxy)
            return True
    raise WebSessionError(f"Chrome 调试端口 {CDP_PORT} 启动超时")


class _Session:
    def __init__(self):
        self._pw = None
        self.browser = None
        self.ctx = None
        self.launched = False

    def __enter__(self):
        self.launched = ensure_browser()
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        try:
            self.browser = self._pw.chromium.connect_over_cdp(CDP_URL)
        except Exception as exc:
            self._pw.stop()
            raise WebSessionError(f"连接 CDP 失败：{type(exc).__name__}: {exc}") from None
        if not self.browser.contexts:
            raise WebSessionError("CDP 已连接但没有浏览器上下文")
        self.ctx = self.browser.contexts[0]
        return self

    def has_cookie(self, domain_part: str, name_part: str | None = None) -> bool:
        for c in self.ctx.cookies():
            if domain_part in c.get("domain", "") and (name_part is None or c.get("name") == name_part):
                if c.get("value"):
                    return True
        return False

    def close_page(self, page) -> None:
        try:
            page.close()
        except Exception:
            pass

    def __exit__(self, *exc):
        try:
            if self.browser:
                self.browser.close()      # 仅断开 CDP，不关闭用户浏览器
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        if self.launched and AUTOCLOSE:
            pids = _profile_pids()
            if pids:
                _kill_pids(pids)
            try:
                PID_FILE.unlink(missing_ok=True)
            except Exception:
                pass
        return False


def _goto(page, url: str, attempts: int = 3, timeout: int = 45000):
    """带重试的页面导航（JSON 端点常常是瞬时超时）。"""
    last = None
    for i in range(attempts):
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            if resp is not None and resp.status == 200:
                return resp
            last = f"HTTP {getattr(resp, 'status', None)}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {str(exc)[:160]}"
        try:
            page.goto("about:blank", timeout=10000)
        except Exception:
            pass
        time.sleep(2 + i * 2)
    raise WebSessionError(f"导航失败（{url}）：{last}")


def _strip_html(text: str) -> str:
    s = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", text or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


FOLO_ENTRIES_JS = """async (fid) => {
  const r = await fetch('https://api.folo.is/entries', {
    method: 'POST', credentials: 'include',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify({view: 0, feedId: fid, limit: 30, withContent: true})
  });
  const t = await r.text();
  return {status: r.status, body: t};
}"""


def folo_fetch(limit: int = 20, max_feeds: int = 12) -> list[Record]:
    """按订阅 feed 拉取最新条目（同源 fetch，使用浏览器 Cookie）。"""
    recs: list[Record] = []
    with _Session() as s:
        if not s.has_cookie("api.folo.is", "__Secure-better-auth.session_token") and \
           not s.has_cookie("follow.is", "__Secure-better-auth.session_token"):
            raise WebSessionError("浏览器中未找到 Folo 登录 Cookie（session_token）")
        page = s.ctx.new_page()
        try:
            _goto(page, "https://api.folo.is/subscriptions?view=0")
            raw = page.inner_text("pre")
            subs = json.loads(raw).get("data") or []
            if not isinstance(subs, list) or not subs:
                raise WebSessionError("Folo 订阅列表为空或结构异常")
            for feed in subs[:max_feeds]:
                fid = feed.get("feedId") or feed.get("id")
                if not fid:
                    continue
                title = None
                feeds_obj = feed.get("feeds")
                if isinstance(feeds_obj, dict):
                    title = feeds_obj.get("title")
                title = title or feed.get("title")
                try:
                    res = page.evaluate(FOLO_ENTRIES_JS, str(fid))
                except Exception:
                    continue
                if not res or res.get("status") != 200:
                    continue
                try:
                    payload = json.loads(res.get("body") or "{}")
                except json.JSONDecodeError:
                    continue
                for wrap in (payload.get("data") or [])[:limit]:
                    item = wrap.get("entries") if isinstance(wrap, dict) else None
                    if not isinstance(item, dict):
                        continue
                    url = (item.get("url") or "").strip()
                    ttl = (item.get("title") or "").strip()
                    if not url.startswith("http") or not ttl:
                        continue
                    content = _strip_html(item.get("content") or "")
                    summary = (item.get("description") or content or "")[:4000]
                    host = url.split("://", 1)[-1].split("/", 1)[0].replace("www.", "")
                    origin = title or host
                    recs.append(Record(
                        url=url, title=ttl,
                        published_at=item.get("publishedAt") or item.get("insertedAt"),
                        summary=summary or None, content=content[:20000] or None,
                        author=item.get("author"), category="info",
                        tags=["folo"] + ([str(title)] if title else []),
                        external_key=f"folo:{item.get('id') or url}",
                        extra={"folo_entry_id": item.get("id"), "folo_feed_id": str(fid),
                               "folo_feed_title": title, "origin_source": origin,
                               "via": "browser_session"},
                    ))
                time.sleep(random.uniform(1.0, 2.0))
        finally:
            s.close_page(page)
    return recs


REDDIT_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || {runtime: {}};
"""

REDDIT_DOM_JS = """() => Array.from(document.querySelectorAll('shreddit-post')).map(el => ({
  title: el.getAttribute('post-title') || ((el.querySelector('[slot="title"]') || {}).textContent || '').trim(),
  permalink: el.getAttribute('permalink') || '',
  created: el.getAttribute('created-timestamp') || '',
  author: el.getAttribute('author') || '',
  score: el.getAttribute('score') || '',
  comments: el.getAttribute('comment-count') || '',
  id: el.getAttribute('id') || ''
}))"""


def _reddit_published(created: str) -> str | None:
    if not created:
        return None
    s = str(created).strip()
    if s.endswith("Z") or "T" in s:
        return s
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(float(s), tz=timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z")
    except Exception:
        return None


def _reddit_json(page, sub: str, limit: int, recs: list[Record]) -> bool:
    """优先尝试 JSON 端点；被 403 时返回 False 交由 DOM 方案。"""
    url = f"https://www.reddit.com/r/{sub}/new.json?limit={min(limit, 100)}&raw_json=1"
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        return False
    if resp is None or resp.status != 200:
        return False
    try:
        data = json.loads(page.inner_text("body"))
    except Exception:
        return False
    for child in ((data.get("data") or {}).get("children") or []):
        d = child.get("data") or {}
        title = d.get("title") or ""
        if not title:
            continue
        created = d.get("created_utc")
        published = None
        if isinstance(created, (int, float)):
            from datetime import datetime, timezone
            published = datetime.fromtimestamp(created, tz=timezone.utc).isoformat(
                timespec="seconds").replace("+00:00", "Z")
        recs.append(Record(
            url=d.get("url_overridden_by_dest") or d.get("url")
                or f"https://www.reddit.com/r/{sub}/comments/{d.get('id')}",
            title=title, published_at=published,
            summary=(d.get("selftext") or "")[:4000] or None,
            author=d.get("author"), category="news", tags=["reddit", sub],
            metrics={"score": d.get("score"), "comments": d.get("num_comments")},
            external_key=f"reddit:{d.get('id')}",
            extra={"subreddit": sub, "reddit_id": d.get("id"),
                   "permalink": d.get("permalink"), "origin_source": sub,
                   "via": "browser_json"}))
    return True


def _reddit_dom(page, sub: str, limit: int, recs: list[Record]) -> bool:
    """JSON 被 403 时的替代：真实浏览器打开 HTML 列表页，读 shreddit-post。"""
    url = f"https://www.reddit.com/r/{sub}/new/"
    resp = None
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        return False
    if resp is not None and resp.status == 403:
        body = ""
        try:
            body = page.inner_text("body")[:160].replace("\n", " ")
        except Exception:
            pass
        raise WebSessionBlocked(f"Reddit HTML 403（出口 IP 被风控拦截）: {body}")
    if resp is None or resp.status != 200:
        return False
    page.wait_for_timeout(3000)
    items: dict[str, dict] = {}
    for _ in range(3):
        try:
            batch = page.evaluate(REDDIT_DOM_JS) or []
        except Exception:
            batch = []
        for it in batch:
            key = it.get("permalink") or it.get("id") or it.get("title")
            if key and key not in items:
                items[key] = it
        if len(items) >= limit:
            break
        try:
            page.evaluate("window.scrollBy(0, 2600)")
        except Exception:
            pass
        page.wait_for_timeout(2500)
    if not items:
        return False
    for it in list(items.values())[:limit]:
        title = (it.get("title") or "").strip()
        permalink = it.get("permalink") or ""
        if not title or not permalink:
            continue
        try:
            score = int(it.get("score") or 0)
        except ValueError:
            score = None
        try:
            comments = int(it.get("comments") or 0)
        except ValueError:
            comments = None
        rid = (it.get("id") or "").replace("t3_", "") or permalink.strip("/").split("/")[-1]
        recs.append(Record(
            url="https://www.reddit.com" + permalink,
            title=title, published_at=_reddit_published(it.get("created") or ""),
            summary=None, author=(it.get("author") or "").replace("u/", "") or None,
            category="news", tags=["reddit", sub],
            metrics={"score": score, "comments": comments},
            external_key=f"reddit:{rid}",
            extra={"subreddit": sub, "reddit_id": rid, "permalink": permalink,
                   "origin_source": sub, "via": "browser_dom"}))
    return True


def reddit_fetch(subreddits: list[str], limit: int = 25) -> list[Record]:
    """Reddit：先试 JSON，403 时回退到真实浏览器 DOM；全败则 BLOCKED。"""
    recs: list[Record] = []
    with _Session() as s:
        page = s.ctx.new_page()
        page.add_init_script(REDDIT_STEALTH_JS)
        try:
            for sub in subreddits:
                ok = False
                try:
                    ok = _reddit_json(page, sub, limit, recs)
                except Exception:
                    ok = False
                if not ok:
                    ok = _reddit_dom(page, sub, limit, recs)
                if not ok:
                    time.sleep(random.uniform(8, 15))
                    continue
                time.sleep(random.uniform(8, 15))   # 真人节奏：8-15 秒
        finally:
            s.close_page(page)
    return recs
