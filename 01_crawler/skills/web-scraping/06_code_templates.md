---
id: WS-06
title: 可运行代码模板
level: 实现
phase: [P3, P4]
triggers: [要代码, 写个脚本, 抄模板, 骨架, 怎么实现]
read_when: 已定性完成，需要落地实现
skip_when: 还没定性（先做 P0/P1，否则抄错模板）
outputs: [侦察脚本, 浏览器模板, 风控探针, 熔断器, 轮换池, 快照 API, 去重, 通知]
next: []
---

# 🧩 Skill 06: 代码模板

> 原则：**模板是起点不是答案**。所有 `{{占位符}}` 必须按目标站替换，所有阈值必须做成可配置。
> 每个模板都可独立运行。导入即用，不依赖本库其他文件。

## 目录

| 模板 | 解决什么 | 阶段 |
|---|---|---|
| [T-01](#t-01-侦察脚本) | 一次打全证据，输出体检报告 | P0/P1 |
| [T-02](#t-02-直连模板带-tls-指纹) | 用 `curl_cffi` 绕开"必须上浏览器" | P1/P3 |
| [T-03](#t-03-patchright-持久化模板) | CDP 级检测 / 需登录 / 长期跑 | P3 |
| [T-04](#t-04-camoufox-模板) | 深度指纹（CF/Akamai） | P3 |
| [T-05](#t-05-风控探针与异常分层) | 识别风控并抛正确异常 | P3/P4 |
| [T-06](#t-06-拟人节奏工具) | 随机延迟 / 滚动 / 点击 | P3/P4 |
| [T-07](#t-07-熔断器) | 别无限重试 | P4 |
| [T-08](#t-08-轮换池) | 账号 / 代理轮换 | P4 |
| [T-09](#t-09-去重与-upsert) | 幂等落库 | P4 |
| [T-10](#t-10-快照--只读-api) | 采集与供数解耦 | P4 |
| [T-11](#t-11-重试窗口调度) | "跑一次失败就空一天" | P4 |
| [T-12](#t-12-通知双层判定) | 通知假成功 | P4 |

---

## T-01 侦察脚本

一次跑完，输出可直接贴进对话的报告。**任何新目标的第一件事。**

```bash
pip install curl_cffi requests -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 两个都装：`curl_cffi` 带 TLS 指纹（优先用），`requests` 作为兜底。
> 只装了其中一个也能跑，两个都没装会直接 `ModuleNotFoundError`。

```python
# recon.py  →  python recon.py "https://target.com/list"
import sys, json, re
from urllib.parse import urlparse

def recon(url: str, ua: str | None = None) -> dict:
    try:
        from curl_cffi import requests as rq          # 优先：带 TLS 指纹
        kw = {"impersonate": "chrome124"}
    except ImportError:
        import requests as rq                          # 兜底
        kw = {}

    headers = {}
    if ua:
        headers["User-Agent"] = ua

    r = rq.get(url, headers=headers, timeout=20, allow_redirects=True, **kw)
    html = r.text
    report = {
        "url": url,
        "final_url": str(r.url),
        "status": r.status_code,
        "bytes": len(r.content),
        "server": r.headers.get("server"),
        "cf_ray": r.headers.get("cf-ray"),
        "content_type": r.headers.get("content-type"),
        "redirects": [str(h.url) for h in r.history],
        # 关键判定
        "looks_spa": bool(re.search(r'<div id="(app|root)"></div>', html)),
        "looks_challenge": any(k in html for k in (
            "请完成安全验证", "cf-challenge", "_cf_chl_opt", "verify you are human")),
        "looks_login_wall": any(k in str(r.url).lower() for k in (
            "login", "passport", "signin", "sso")),
        "has_embedded_json": "__INITIAL_STATE__" in html or "__NUXT__" in html,
        "text_len": len(re.sub(r"<[^>]+>", "", html)),
    }
    # 打分：帮你快速定性
    b, t = report["bytes"], report["text_len"]
    if report["status"] >= 400:                  report["verdict"] = "http_error→查 A 组"
    elif report["looks_challenge"]:              report["verdict"] = "JS挑战/验证页→真浏览器 + C-11"
    elif report["looks_login_wall"]:             report["verdict"] = "登录墙→WS-03 §五"
    elif report["looks_spa"] and t < 200:        report["verdict"] = "SPA空壳→去 Network 找 XHR"
    elif t < 200:                                report["verdict"] = "内容极少→软拦截 或 需渲染"
    elif t < 1500 and b < 8000:                  report["verdict"] = "小页面→确认这就是全部内容"
    else:                                        report["verdict"] = "有真内容→直接解析"
    return report

if __name__ == "__main__":
    url = sys.argv[1]
    for ua in (None, "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"):
        print(json.dumps(recon(url, ua), ensure_ascii=False, indent=2))
        print("-" * 60)
```

> **读报告的方法**：两次结果（无 UA / 有 UA）不一致 → 说明在查 UA；`bytes` 小且 `looks_spa` 为真 → 别再折腾 HTTP 了，去抓 XHR。
>
> **verdict 是启发式不是判据**。实测 `example.com` 只有 577 字节但完全正常，所以判定用「文本长度 + 字节数」联合，而不是单纯卡 5000 字节。
> 任何自动判定都要用真实数据校准一次再信 —— 这也是本库 C7 约束的具体体现。

---

## T-02 直连模板（带 TLS 指纹）

**在动用浏览器之前，先试这个。** 很多"必须上浏览器"的站它就能过。

```python
from curl_cffi import requests

def fetch(url: str, *, referer: str | None = None, impersonate: str = "chrome124"):
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    if referer:
        headers["Referer"] = referer
    r = requests.get(url, headers=headers, impersonate=impersonate, timeout=20)
    r.raise_for_status()
    return r
```

安装：`pip install curl_cffi -i https://pypi.tuna.tsinghua.edu.cn/simple`

> `impersonate` 可选：`chrome99`~`chrome124`、`safari17_0`、`edge101`。
> **版本要与 UA 对齐**，别写 `chrome124` 却在 header 里冒充 131。

---

## T-03 patchright 持久化模板

CDP 级检测 / 需登录 / 长期跑，**首选这一个**。完整原理见 [WS-02](./02_cdp_detection_bypass.md)。

```python
# browser_runner.py
from patchright.sync_api import sync_playwright, TimeoutError as PWTimeout

PROFILE = "./browser_profile"          # 固定目录 = 登录态 + 指纹自然沉淀
CHANNEL = "msedge"                     # 本机有 Edge 就用它，省下 Chromium 下载
LOGIN_COOKIE = "{{改成目标站的登录 cookie 名，如 zp_at}}"   # 用于判断是否已登录

class LoginRequired(Exception): ...
class RiskControl(Exception): ...

def is_logged_in(ctx) -> bool:
    return LOGIN_COOKIE in {c["name"] for c in ctx.cookies()}

def ensure_login(ctx):
    """首次运行扫码/密码登录，之后 profile 复用。"""
    if is_logged_in(ctx):
        return
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("{{登录页 URL}}", wait_until="domcontentloaded")
    print("请手动完成登录，最多等 180 秒 ...")
    for _ in range(120):
        page.wait_for_timeout(1500)
        if is_logged_in(ctx):
            print("[OK] 登录成功，已写入 profile")
            return
    raise LoginRequired("登录超时")

def health(page) -> dict:
    """三项体检：任何一项不对就不要往下走。"""
    return {
        "url": page.url,
        "body_len": len(page.inner_text("body")),
        "html_len": len(page.content()),
        "about_blank": page.url.startswith("about:blank"),
    }

def run(target_url: str):
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE,
            channel=CHANNEL,
            headless=False,          # 首次务必有头；稳定后可改 True 观察是否退化
            no_viewport=True,        # 关键：别伪造固定视口
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        try:
            ensure_login(ctx)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            h = health(page)
            print(h)
            if h["about_blank"] or h["body_len"] < 20:
                raise RiskControl(f"疑似 CDP 检测: {h}")
            if "login" in h["url"].lower() or "passport" in h["url"].lower():
                raise LoginRequired(h["url"])

            # ↓ 你的解析逻辑
            return page
        finally:
            ctx.close()

if __name__ == "__main__":
    run("{{目标 URL}}")
```

### 三不要（违反任一条可能前功尽弃）
1. 不要 `add_init_script` 注入 stealth —— patchright 已处理，再注入会在调用栈里留下可疑帧
2. 不要覆盖 `user_agent` —— 真内核的 UA 天然正确
3. 不要设固定 `viewport` —— 用 `no_viewport=True`

---

## T-04 Camoufox 模板

深度指纹（Cloudflare / Akamai / DataDome）。Firefox 基底，指纹面与 Chromium 自动化不同。

```python
from camoufox.sync_api import Camoufox
from camoufox import DefaultAddons

with Camoufox(
    headless=True,
    humanize=True,                                  # 拟人化输入/滚动
    locale="zh-CN",
    geoip=True,                                     # 按出口 IP 自动对齐时区/语言
    exclude_addons=[DefaultAddons.UBO],             # UBO 会 451，关掉
    os=["windows", "macos"],                        # 随机选一个 OS 画像
) as browser:
    page = browser.new_page()
    page.goto("{{URL}}", wait_until="domcontentloaded")
    print(page.title(), len(page.content()))
```

> **注意**：Camoufox 是 Firefox 内核，`channel="chrome"`、Chromium 专属启动参数、部分 CSS 行为都不适用。
> 换内核 = 重写选择器与等待逻辑，评估成本后再换。

---

## T-05 风控探针与异常分层

把"检测"和"处置"分开：探针只负责抛异常，上层决定换号还是熔断。

```python
class ScrapeError(Exception): ...
class LoginRequired(ScrapeError): ...
class RiskControl(ScrapeError): ...
class ParseFailed(ScrapeError): ...
class Throttled(ScrapeError): ...

# 按目标站改这些选择器；能用多个就给多个候选
RISK_POPUP_SELECTORS = [
    "div.baxia-dialog-mask",           # 滑块/验证弹层
    "div.J_MIDDLEWARE_FRAME_WIDGET",
    "iframe[src*='captcha']",
]
RISK_API_TOKENS = ("FAIL_SYS_USER_VALIDATE", "RGV587_ERROR", "请进行滑块验证")
LOGIN_URL_TOKENS = ("passport.", "login", "signin")

def check_risk(page, *, popup_timeout: int = 2000):
    """短超时轮询判定：比 is_visible() 可靠，没有竞态。"""
    from patchright.sync_api import TimeoutError as PWTimeout   # 或 playwright
    for sel in RISK_POPUP_SELECTORS:
        try:
            page.locator(sel).first.wait_for(state="visible", timeout=popup_timeout)
            raise RiskControl(f"popup:{sel}")
        except PWTimeout:
            continue

def check_login(page):
    if any(t in page.url.lower() for t in LOGIN_URL_TOKENS):
        raise LoginRequired(page.url)

def check_api_risk(payload: dict | str):
    s = str(payload)
    if any(t in s for t in RISK_API_TOKENS):
        raise RiskControl(f"api:{s[:200]}")
```

**上层处置表**：

| 异常 | 处置 |
|---|---|
| `LoginRequired` | 不重试。通知人工更新凭据；凭据文件 mtime 变化后自动恢复 |
| `RiskControl` | 先随机睡 3~60s，**再**换代理；连续 2 次则熔断 |
| `Throttled` | 指数退避，不换号（换号也没用） |
| `ParseFailed` | 记录 HTML 片段，跳过单条，不中断任务 |
| 其他 | 有限重试 2 次后记失败 |

---

## T-06 拟人节奏工具

**所有固定 `sleep(3)` 都换成这个。** 固定间隔本身就是风控特征。

```python
import random, time

def rand_sleep(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))

def human_scroll(page, steps: int = 3):
    for _ in range(steps):
        page.mouse.wheel(0, random.randint(200, 700))
        rand_sleep(0.4, 1.2)

def human_click(page, locator):
    locator.hover()
    rand_sleep(0.2, 0.6)
    box = locator.bounding_box()
    if box:   # 点在元素内部随机位置，不是正中
        page.mouse.click(
            box["x"] + box["width"] * random.uniform(0.25, 0.75),
            box["y"] + box["height"] * random.uniform(0.25, 0.75),
        )
    else:
        locator.click()
    rand_sleep(0.3, 0.9)

def backoff(attempt: int, base: float = 2.0, cap: float = 120.0) -> float:
    """指数退避 + 抖动。用于 429 / 5xx。"""
    d = min(cap, base * (2 ** attempt)) * random.uniform(0.6, 1.4)
    time.sleep(d)
    return d
```

### 节奏基线（起点值，按站点调）

| 环节 | 区间 |
|---|---|
| 页面加载后 | 1~3s |
| 点击/输入之间 | 0.3~0.9s |
| 进详情页前 | 2~4s |
| 单条数据处理完 | 5~10s |
| 翻页之间 | 10~15s |
| 命中风控后 | 3~60s |

---

## T-07 熔断器

登录态挂了别无限重试。精简版，跨平台。

```python
import json, os, time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

try:
    from filelock import FileLock          # pip install filelock
except ImportError:
    FileLock = None

class FailureGuard:
    def __init__(self, path="logs/guard.json", threshold=3,
                 pause_seconds=86400, tz=timezone(timedelta(hours=8))):
        self.path, self.threshold = path, threshold
        self.pause_seconds, self.tz = pause_seconds, tz
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    # ---------- 原子读写 ----------
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
                return d if isinstance(d, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception:                      # 损坏则留证据，不覆盖
            os.replace(self.path, f"{self.path}.corrupt.{int(time.time())}")
            return {}

    def _save(self, d):
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def _update(self, key, fn):
        lock = FileLock(self.path + ".lock") if FileLock else None
        if lock:
            with lock:
                d = self._load(); e = fn(d.get(key) or {}); d[key] = e; self._save(d)
        else:
            d = self._load(); e = fn(d.get(key) or {}); d[key] = e; self._save(d)
        return e

    # ---------- 对外接口 ----------
    def check(self, key, cookie_path=None) -> tuple[bool, str]:
        """返回 (是否跳过, 原因)。cookie 文件变化 = 自动恢复。"""
        now = datetime.now(self.tz)
        e = self._load().get(key) or {}
        paused_until = e.get("paused_until")

        # 关键：凭据更新后自动解除暂停
        if paused_until and cookie_path and os.path.exists(cookie_path):
            prev = e.get("cookie_mtime")
            if prev and os.path.getmtime(cookie_path) > prev + 1e-6:
                self.success(key); return False, "cookie_updated"

        if paused_until and now < datetime.fromisoformat(paused_until):
            return True, e.get("last_reason", "unknown")
        return False, "ok"

    def success(self, key):
        self._update(key, lambda e: {"consecutive": 0, "paused_until": None,
                                     "last_reason": None})

    def failure(self, key, reason, *, cookie_path=None, pause_immediately=False):
        now = datetime.now(self.tz)
        def fn(e):
            n = int(e.get("consecutive", 0)) + 1
            e.update(consecutive=n, last_reason=str(reason)[:500],
                     last_failure_at=now.isoformat())
            if cookie_path and os.path.exists(cookie_path):
                e["cookie_mtime"] = os.path.getmtime(cookie_path)
            thr = 1 if pause_immediately else self.threshold
            if n >= thr:
                e["paused_until"] = (now + timedelta(seconds=self.pause_seconds)).isoformat()
            return e
        return self._update(key, fn)
```

**三个必须保留的设计**：① 原子写（临时文件 + `os.replace`）② 损坏文件改名留证 ③ cookie mtime 变化自动恢复。

---

## T-08 轮换池

```python
import random, time
from dataclasses import dataclass, field

@dataclass
class Item:
    value: str
    last_error: str | None = None

class RotationPool:
    """账号池 / 代理池通用。黑名单带 TTL，不永久封禁。"""
    def __init__(self, items, name="pool", blacklist_ttl=300):
        self.items = [Item(v) for v in items if v]
        self.name, self.ttl = name, max(0, blacklist_ttl)
        self._bad: dict[str, float] = {}

    def _alive(self):
        now = time.time()
        for k in [k for k, t in self._bad.items() if t <= now]:
            self._bad.pop(k)
        return [i for i in self.items if i.value not in self._bad]

    def pick(self) -> Item | None:
        alive = self._alive()
        # random 而非轮询：轮询在风控看来是周期指纹
        return random.choice(alive) if alive else None

    def mark_bad(self, item: Item | None, reason=""):
        if not item: return
        item.last_error = reason
        if self.ttl > 0:
            self._bad[item.value] = time.time() + self.ttl

    def stats(self):
        return {"name": self.name, "total": len(self.items),
                "alive": len(self._alive()), "bad": len(self._bad)}
```

**用法**：`account_pool` 与 `proxy_pool` 共用这个类。模式选 `per_task`（每任务换一次，摊薄单号请求量）或 `on_failure`（失败才换，省配额）。

---

## T-09 去重与 upsert

**幂等的关键：唯一键 + ON CONFLICT。** 重跑不会产生脏数据。

```python
import sqlite3, hashlib
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from datetime import datetime, timezone

TRACKING = {"utm_source","utm_medium","utm_campaign","utm_term","utm_content",
            "spm","from","share_token","ref"}

def canonical_url(url: str) -> str:
    """去掉追踪参数、统一大小写主机、去尾斜杠。唯一键就用它。"""
    s = urlsplit(url.strip())
    q = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True)
         if k.lower() not in TRACKING]
    path = s.path.rstrip("/") or "/"
    return urlunsplit((s.scheme.lower(), s.netloc.lower(), path, urlencode(sorted(q)), ""))

DDL = """
CREATE TABLE IF NOT EXISTS items (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical    TEXT UNIQUE NOT NULL,
  source       TEXT NOT NULL,
  title        TEXT,
  price        REAL,
  raw          TEXT,
  status       TEXT NOT NULL DEFAULT 'active',   -- active / hidden / expired
  first_seen   TEXT NOT NULL,
  last_seen    TEXT NOT NULL,
  seen_count   INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_source_status ON items(source, status);
"""

def upsert(conn: sqlite3.Connection, *, source: str, url: str,
           title: str, price: float | None, raw: str) -> bool:
    """返回 True = 新数据（可触发通知），False = 已存在（只更新）。"""
    now = datetime.now(timezone.utc).isoformat()
    c = conn.cursor()
    key = canonical_url(url)
    c.execute("SELECT 1 FROM items WHERE canonical=?", (key,))
    existed = c.fetchone() is not None
    c.execute("""
        INSERT INTO items(canonical, source, title, price, raw, first_seen, last_seen)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(canonical) DO UPDATE SET
            title=excluded.title, price=excluded.price, raw=excluded.raw,
            last_seen=excluded.last_seen, seen_count=seen_count+1
    """, (key, source, title, price, raw, now, now))
    conn.commit()
    return not existed
```

**去重粒度要跟业务语义走**：
- "同一商品降价" → **不是重复**，要记价格历史（独立表，按 `(canonical, day)` 唯一）
- "同一天同一商品被扫到 10 次" → 是重复，只更新 `last_seen`

---

## T-10 快照 → 只读 API

采集与供数解耦（[WS-04](./04_aggregator_pipeline_design.md)）。抓取端写文件，API 只读。

```python
# app.py  →  uvicorn app:app --port 8000
import json, glob, os
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, PlainTextResponse

SNAP_DIR = "./snapshots"          # 抓取端写这里: {name}/{YYYY-MM-DD}.json
app = FastAPI(title="snapshot-api")

def load(name: str, date: str | None = None) -> dict | None:
    if date:
        p = os.path.join(SNAP_DIR, name, f"{date}.json")
        files = [p] if os.path.exists(p) else []
    else:
        files = sorted(glob.glob(os.path.join(SNAP_DIR, name, "*.json")), reverse=True)
    if not files:
        return None
    with open(files[0], encoding="utf-8") as f:
        d = json.load(f)
    d.setdefault("_snapshot_file", os.path.basename(files[0]))
    return d

def to_text(d: dict) -> str:
    lines = [f"# {d.get('title', '')}  更新于 {d.get('updated', '')}"]
    for i, it in enumerate(d.get("items", []), 1):
        lines.append(f"{i}. {it.get('title')}  {it.get('price', '')}")
    return "\n".join(lines)

def to_md(d: dict) -> str:
    rows = ["| # | 标题 | 价格 |", "|---|---|---|"]
    for i, it in enumerate(d.get("items", []), 1):
        rows.append(f"| {i} | {it.get('title','')} | {it.get('price','')} |")
    return f"# {d.get('title','')}\n\n" + "\n".join(rows)

@app.get("/v1/{name}")
def get_data(name: str,
             encoding: str = Query("json", pattern="^(json|text|markdown)$"),
             date: str | None = None):
    d = load(name, date)
    if d is None:
        return JSONResponse({"code": 404, "message": "no snapshot", "data": None},
                            status_code=404)
    if encoding == "text":
        return PlainTextResponse(to_text(d), media_type="text/plain; charset=utf-8")
    if encoding == "markdown":
        return PlainTextResponse(to_md(d), media_type="text/markdown; charset=utf-8")
    return {"code": 0, "message": "ok", "data": d}
```

**必须做的两件事**：
1. **降级要显式**：返回旧快照时带上 `stale: true` 和 `updated`，别让用户拿旧数据当新的
2. **加 `/llms.txt`**：把可用接口、参数、返回结构写成一段 Markdown，让 AI 能自助调用

---

## T-11 重试窗口调度

"定 7 点跑一次，失败就空一天"是不可接受的。**在窗口内反复试，成功即停。**

```python
import time, logging
from datetime import datetime, time as dtime, timedelta, timezone

log = logging.getLogger(__name__)
TZ = timezone(timedelta(hours=8))

def run_with_window(job, *, window_end=dtime(10, 0), interval=1800, tz=TZ):
    """在 [now, 今天 window_end) 内每 interval 秒试一次，成功即停。
    典型场景：数据源每天早上不定时更新。"""
    now = datetime.now(tz)
    deadline = now.replace(hour=window_end.hour, minute=window_end.minute,
                           second=0, microsecond=0)
    if deadline <= now:
        deadline += timedelta(days=1)

    attempt = 0
    while datetime.now(tz) < deadline:
        attempt += 1
        try:
            result = job()
            if result:
                log.info("第 %d 次尝试成功", attempt)
                return result
            log.info("第 %d 次尝试无新数据，%d 秒后重试", attempt, interval)
        except Exception as e:
            log.warning("第 %d 次尝试失败: %s", attempt, e)
        time.sleep(interval)
    log.error("窗口耗尽，未拿到数据（保留上一版快照）")
    return None
```

---

## T-12 通知双层判定

HTTP 200 不代表发送成功。所有 webhook 都要查业务码。

```python
import requests, logging
log = logging.getLogger(__name__)

class NotifyError(Exception): ...

def notify(webhook: str, text: str, *, channel: str = "generic") -> None:
    if channel == "wecom":                 # 企业微信机器人
        payload = {"msgtype": "text", "text": {"content": text}}
        ok_codes = (0,)
        business_key = "errcode"
    else:
        payload = {"text": text}
        ok_codes = (0, 200, "0", "ok", "success")
        business_key = "code"

    r = requests.post(webhook, json=payload, timeout=10)
    if r.status_code != 200:
        raise NotifyError(f"http {r.status_code}: {r.text[:200]}")

    try:
        body = r.json()
    except ValueError:
        return                              # 纯文本回执，视为成功

    val = body.get(business_key)
    if val is not None and val not in ok_codes:
        raise NotifyError(f"业务失败 {business_key}={val}: {body}")
```

**消息体要自足**：`任务名 + 命中原因 + 价格 + 链接 + 时间`。少一项用户就得回后台查。
企业微信发纯文本，别发 markdown（换行会被吃掉）。

---

## 组装方式

```
最简（一次性抓取）
  T-01 侦察 → T-02 直连 → T-09 落库

中等（要登录 / 有反爬）
  T-01 → T-02 试 → T-03 patchright → T-05 探针 → T-06 节奏 → T-09 落库

系统（长期跑）
  T-01 → T-03 → T-05 + T-06 + T-07 熔断 + T-08 轮换 + T-09 + T-12 通知

供数（对外 API）
  T-11 定时 → 抓取(上面任一套) → 写快照 → T-10 只读 API
```

> **顺序不能反**：先能稳定拿 1 条（P3），再加熔断轮换（P4）。在单条都拿不稳的时候上并发和轮换池，只会把问题放大。
