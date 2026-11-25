---
id: WS-05
title: 故障查表（症状 → 根因 → 动作 → 验证）
level: 排障
phase: [P1, P3, P4, P5]
triggers: [报错, 昨天能跑今天不行, 数据不对, 超时, 空结果, 验证码, 429, 白屏, 内存涨]
read_when: 任何"它不工作了"的时刻。先查表，再决定读哪篇
skip_when: 全新项目尚未动手（从 SKILL.md P0 开始）
outputs: [根因判定, 单条可执行动作, 验证命令]
next: [对应主文档]
---

# 🩺 Skill 05: 故障查表

> 这是整个库使用频率最高的一篇。**先查表定位，再去读对应文档** —— 不要从方法论开始重读一遍。
> 用法：在下面的主表里按"你观察到的现象"找行，执行"首个动作"，按"判定"分流。

## 0. 黄金排查序列（5 分钟，能解决 80% 的问题）

按顺序跑，**命中即停**，不要跳步：

```bash
# ① 出口 IP 是什么？是不是机房 IP / 被拉黑的段
curl -s https://api.ipify.org; echo

# ② 裸 HTTP 到底拿到什么（状态码 + 字节数是第一证据）
curl -s -o /tmp/r.html -w "code=%{http_code} bytes=%{size_download} time=%{time_total}\n" "URL"

# ③ 拿到的是空壳、拦截页、还是真内容
head -c 800 /tmp/r.html

# ④ 带浏览器头再试（顺序：UA → Accept → Referer）
curl -s -o /dev/null -w "code=%{http_code} bytes=%{size_download}\n" \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" \
  -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
  -H "Accept-Language: zh-CN,zh;q=0.9" "URL"
```

```python
# ⑤ 浏览器侧三项体检（任何"拿不到数据"都先打这三行）
print("url     :", page.url)                        # about:blank ?
print("body_len:", len(page.inner_text("body")))     # 0~15 ?
print("html_len:", len(page.content()))              # 只有几 KB ?
```

**判定**：
- ② 的 bytes < 5000 且 ⑤ 的 html_len 也小 → **空壳 / 拦截页** → 走 C 组
- ② 的 bytes 正常但 ⑤ 的 body_len 是 0~15 → **CDP 级检测** → 走 C-09
- ② 正常、⑤ 也正常，但字段取不到 → **解析问题** → 走 D 组
- 都不正常且换网络就好 → **IP 层** → 走 A 组

---

## 1. 主表

| ID | 症状（可观察） | 概率排序的根因 | 首个动作 | 命中则去 |
|---|---|---|---|---|
| F-01 | 连接被拒 / 一直超时 | ① IP 被封 ② DNS 污染 ③ 目标只接受特定地区 IP | `curl -v` 看卡在 DNS 还是 TCP 握手 | A-01 |
| F-02 | 403 / 429 / 503 | ① 频率限制 ② WAF 指纹 ③ 缺 header | 看响应头有无 `retry-after` / `cf-ray` | A-02 / F-04 |
| F-03 | 200 但只有几 KB | ① SPA 空壳 ② 软拦截页（假 200） | `grep -c 'id="app"\|id="root"'` | A-03 |
| F-04 | 403 + `server: cloudflare` / `cf-ray` | Cloudflare WAF | 换 Camoufox 或真内核 | A-04 |
| F-05 | 本机能通，服务器不通 | 机房 IP 段被针对 | 服务器上跑 `curl ipify` 对比 | A-05 |
| F-06 | 同样的头，curl 通、python 不通 | TLS / HTTP2 指纹（JA3） | 换 `curl_cffi` 或 `httpx[http2]` | B-06 |
| F-07 | 偶发 403，重试就好 | 缺 `sec-ch-ua` 一类客户端提示头 | 补全 UA 相关头 | B-07 |
| F-08 | 上传/大响应失败 | HTTP/2 流控或分块问题 | 降级 `--http1.1` 试 | B-08 |
| F-09 | `page.url` 变 `about:blank` | CDP 级检测 | 立刻停掉指纹折腾，读 WS-02 | C-09 |
| F-10 | `body_len` 0~15 | CDP 级检测 / 渲染被掐断 | 同上 | C-09 |
| F-11 | 手动能开，脚本一点击就跳验证 | 行为风控（轨迹/间隔/顺序） | 降频 + 加随机滚动 | C-11 |
| F-12 | `headless=True` 挂，`False` 通 | Headless 特征检测 | 改有头；或换 Camoufox | C-12 |
| F-13 | 白屏，但 header 里带 `sec-fetch-*` | 浏览器托管头污染（导航被当 CORS） | 剔除 `sec-*` / `cookie` / `host` 等头 | C-13 |
| F-14 | 页面截图只有 loading 骨架 | 前端 JS 异常 | 挂 `page.on("console")` 看报错 | C-14 |
| F-15 | 数字变方框 / 乱码 / 每次不同 | 字体混淆（动态 @font-face） | 检查 CSS 是否加载自定义字体 | D-15 |
| F-16 | 数据看起来合理但是假的 | 蜜罐投毒（honeypot 字段） | 对比页面显示值与接口值 | D-16 |
| F-17 | 选择器 `count() == 0` | ① 类名哈希变了 ② 结构改版 ③ 内容没渲染完 | 打出 page.content() 片段人工看 | D-17 |
| F-18 | 价格/销量是图片 | 反 OCR / 反抓取 | 图床 URL + OCR，或换数据源 | D-18 |
| F-19 | 接口字段是 base64 / 十六进制长串 | 字段加密 | 走签名/加密逆向 | D-19 → WS-07 |
| F-20 | 302 到登录页 | 凭据过期 | 检查 cookie 是否存在/过期 | E-20 |
| F-21 | 登录了但接口 401 | token 未刷新 / 需要额外 cookie（如 `_m_h5_tk`） | 抓一次成功请求对比 cookie 集合 | E-21 |
| F-22 | cookie 有效却被风控 | 会话不一致（IP/UA/设备变了） | 固定出口 + 固定 profile | E-22 |
| F-23 | 每次启动都要重新登录 | 用了临时 context 而非 persistent | 改 `launch_persistent_context` | E-23 |
| F-24 | 上周能跑，这周不行 | ① 改版 ② 防护升级 ③ 接口变更 | 做"三 diff"（见 F-24 详解） | F-24 |
| F-25 | 接口 404 / 返回空 data | 接口路径或参数改了 | 重新抓 XHR | F-25 |
| F-26 | 新请求多了一个必填参数 | 新增签名/校验 | 对比新旧请求参数集 | F-26 → WS-07 |
| F-27 | 数据量突然减半 | ① 分页 limit 变小 ② 部分结果被过滤 ③ 需登录才全量 | 打印每页条数 | F-27 |
| F-28 | 第一次跑有数据，第二次跑全空 | 去重逻辑误杀 / 游标没重置 | 检查去重键与游标 | F-28 |
| F-29 | 内存持续涨 / 进程被 OOM 杀 | 浏览器没关 / crashpad 泄 | 加 `finally: close` + 关 crash reporter | G-29 |
| F-30 | Docker 里必崩，本地正常 | `/dev/shm` 太小 / sandbox | `--disable-dev-shm-usage --no-sandbox` | G-30 |
| F-31 | 并发上去失败率爆炸 | 并发与风控正相关 | 并发降到 1~2 再逐步试 | G-31 |
| F-32 | 任务卡死不退出 | 缺全局 timeout / 未 join 子任务 | 加 `wait_for_timeout` 与 `join()` | G-32 |
| F-33 | 通知发了但用户没收到 | HTTP 200 但业务码非 0 | 解析响应 body 的 `code` | G-33 |

---

## 2. A 组：网络与 IP 层

### A-01 连接层失败
```bash
curl -v --max-time 10 "URL" 2>&1 | tail -20
```
- 卡在 `Trying <ip>...` → TCP 不通，IP 被封或端口过滤
- 卡在 `Could not resolve host` → DNS 问题
- 握手后立即 RST → 目标主动拒绝（常见于机房 IP）

**修复顺序**：换出口（手机热点最便宜）→ 再谈代码。**IP 不通时改任何代码都是无效动作。**

### A-02 频率限制
```bash
curl -sI "URL" | grep -iE "retry-after|x-ratelimit|429"
```
- 有 `retry-after: N` → 老实等 N 秒，并把全局间隔调到 `N/并发数` 以上
- 无明确头但偶发 429 → 用指数退避 + 抖动：`sleep = min(cap, base * 2**n) * random(0.5, 1.5)`

**关键认知**：429 是**最友好的信号**，它在明确告诉你"慢点"。真正危险的是不报错但给你假数据。

### A-03 假 200（软拦截）
```bash
curl -s "URL" | head -c 500
```
三种形态：
1. `<div id="app"></div>` + 一堆 `<script>` → SPA，去 P0 找 XHR
2. 一段 JS 挑战脚本（`document.cookie=...; location.reload()`）→ JS 挑战，需真浏览器
3. 验证页 HTML（"请完成安全验证"）→ 行为风控，走 C-11

### A-04 Cloudflare / Akamai
判定：
```bash
curl -sI "URL" | grep -iE "server|cf-ray|cf-cache|akamai"
```
- `server: cloudflare` + `cf-ray` → CF。静态页可试 `curl_cffi` 模拟 TLS 指纹；有 JS 挑战则必须真浏览器
- `server: AkamaiGHost` → Akamai，指纹更严，优先 Camoufox
- 响应头 `_abck` / `bm_sz` cookie → Akamai Bot Manager，需要维持 cookie 生命周期

**不要做的事**：不要用 `playwright-stealth` 硬扛 CF 的 JS 挑战，成功率很低且不稳定。

### A-05 环境差异（本机通/服务器不通）
机房 IP 段是公开的（AWS/GCP/阿里云段），很多站点直接拉黑整段。
**判定**：服务器上 `curl ipify` 与本地对比，看 ASN。
**修复**：住宅/移动出口、自建代理池（见 WS-06 T-05）。

---

## 3. B 组：传输与协议层

### B-06 TLS / HTTP2 指纹
**症状**：完全相同的 header，`curl` 通但 `requests` 403；或反过来。
**原因**：服务端看 JA3/JA4 指纹（TLS 客户端 hello 的密码套件顺序、扩展顺序）。

**修复优先级**：
1. `pip install curl_cffi` → `requests.get(url, impersonate="chrome")` ← 成本最低，覆盖大部分场景
2. `httpx` 开 HTTP/2：`httpx.Client(http2=True)`
3. 真浏览器

```python
from curl_cffi import requests
r = requests.get(url, impersonate="chrome124", timeout=15)
```
> 这是近两年最被低估的一招：**很多"必须上浏览器"的站，`curl_cffi` 就够了**。先试它，再考虑 Playwright。

### B-07 客户端提示头（Client Hints）
现代 Chrome 会发 `sec-ch-ua`、`sec-ch-ua-mobile`、`sec-ch-ua-platform`。只发 UA 不发这些，等于告诉对方"我是个假 Chrome"。
```python
headers = {
    "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
```
**注意版本一致性**：UA 里写 131，`sec-ch-ua` 也必须是 131。

### B-08 HTTP/2 相关问题
大响应、上传、长连接场景下偶发失败。先试 `--http1.1` 排除。

---

## 4. C 组：浏览器与检测层

### C-09 / C-10 CDP 级检测（本篇最高频）
**决定性证据**（三条全打）：
```python
print(page.url)                          # about:blank ?
print(len(page.inner_text("body")))      # 0~15 ?
print(len(page.content()))               # 只有几 KB ?
```
命中 → **停止所有指纹调参**，直接上 `patchright + launch_persistent_context`。完整方案见 [WS-02](./02_cdp_detection_bypass.md)。

**为什么停止调参**：CDP 检测发生在协议层（`Runtime.enable` 副作用、注入脚本的调用栈帧、exposeBinding 对象可枚举）。改 UA/时区/stealth 脚本都在 JS 层，**维度不对，怎么改都没用**。

### C-11 行为风控
症状：手动能开，脚本一"点击"就被拦；或浏览 3~5 页后必弹验证。
**根因**：风控看的是**时序特征**——间隔太规律、无鼠标轨迹、滚动模式机械、点击坐标过于居中。

**修复**（按性价比排序）：
1. **所有间隔改成随机区间**（这一条通常就能解决大半）
2. 加随机滚动：`page.mouse.wheel(0, random.randint(200, 700))`
3. 点击前加微小停顿 + 随机偏移
4. 别用 `page.click(selector)` 直接点，先 `hover` 再 `click`

### C-12 Headless 检测
先试有头。若有头通过、无头失败，说明对方查了 `HeadlessChrome`（UA 里就有）或窗口尺寸异常。
- 有头环境不存在时的替代：`xvfb`（Linux）或 Camoufox（它默认就处理得较好）
- 不要试图用 `--headless=new` 蒙混，现代检测能分辨

### C-13 浏览器托管头污染（**最容易误判成反爬**）
症状：页面白屏，DOM 几乎是空的，但状态码 200、请求头看着也正常。
根因：你把一个 **XHR 请求**的 header 全套到了**文档导航**上，其中 `sec-fetch-mode: cors` 之类会让浏览器把导航当跨域请求处理 → 白屏。

**必须剔除的头**（浏览器自己会填）：
```python
BROWSER_MANAGED = {
    "accept","accept-encoding","authorization","connection","content-length",
    "content-type","cookie","host","origin","proxy-authorization","referer",
    "sec-fetch-dest","sec-fetch-mode","sec-fetch-site","sec-fetch-user",
    "upgrade-insecure-requests","user-agent",
}
```
详见 [WS-03](./03_deep_site_scraper_engineering.md) 第五节。

### C-14 前端 JS 异常
```python
page.on("console", lambda m: print("CONSOLE", m.type, m.text))
page.on("pageerror", lambda e: print("PAGEERROR", e))
```
先看报错再改代码。空白页有一半是前端自己崩了（比如某个接口 401 导致整页渲染失败）。

---

## 5. D 组：数据与解析层

### D-15 字体混淆
症状：抓下来的数字是 `Ö§×¾` 或每次都不一样；复制到记事本也是乱码；截图看正常。
判定：`page.content()` 里搜 `@font-face` 且 `src: url(data:font` → 动态字体。
处理：
1. 抓字体文件 → 用 `fontTools` 解析字形轮廓 → 建立"字形→真实数字"映射
2. 更省事：用 OCR（截图 + 数字识别），但慢
3. **最省事**：换数据源（能找到同数据的干净接口就别硬解字体）

### D-16 蜜罐投毒
症状：接口返回的数据里有一部分是假的（价格异常低、字段互相矛盾），但结构完全正常。
判定：**页面显示值 vs 接口返回值**逐条对比。不一致的就是投毒字段。
处理：找到投毒规则（常见：某个 class 的元素被 `display:none` 隐藏），只保留可见项。

### D-17 选择器失效
```python
print(page.content()[:2000])                      # 先看真实 HTML
print(page.locator("帮你猜的选择器").count())      # 必须 >0 才算存在
```
**规则**：
- 不要相信任何"看起来合理"的选择器，**先打 count 验证**
- CSS Modules：`[class*='areaWrap']` 前缀匹配 > 精确 class
- 优先用文本定位（`get_by_text`）或结构定位（`:scope > div`）
- 加等待：`wait_for_selector` 比 `sleep` 靠谱，但要有超时上限

### D-18 图片化数据
价格/销量做成图片。方案：拿到图片 URL → OCR（`ddddocr` 轻量）→ 缓存映射（同一张图只识别一次）。
**先想想值不值**：如果只有几个位置，人工规则或换源更快。

### D-19 字段加密
```python
import base64, binascii
# 特征：长度是 4 的倍数、结尾有 = 或 == → base64
# 特征：全十六进制且长度 16/32 的倍数 → AES 密文
```
→ 转 [WS-07](./07_js_signature_reverse.md).

---

## 6. E 组：凭据与会话层

### E-20 凭据过期
```python
if "passport" in page.url or "login" in page.url:   # 登录墙特征
    raise LoginRequiredError(page.url)
```
**关键**：登录失效往往**不报错**，是静默 302。每次 `goto` 后都要检查 URL，否则你会等到 15 秒超时然后误判"改版了"。

### E-21 登录了但接口 401
常见于需要**双 token** 的站点：cookie 之外还要一个从页面/接口动态拿的 token（如 `_m_h5_tk`、`x-csrf-token`）。
**做法**：抓一次**手动操作时成功**的请求，把它的完整 header + cookie 抄下来，与你的请求做 diff。

### E-22 会话不一致
你换了 IP 但复用了旧 cookie；或换了 UA 但 cookie 里的设备标识没变 → 风控判定"账号被盗用"。
**规则：一个账号 = 一个出口 IP = 一个 profile = 一个 UA，四者绑定，要么一起换要么都不换。**

### E-23 每次都要重登
用了 `browser.new_context()` / `launch()`+`storage_state`，IndexedDB、localStorage、指纹种子每次重置。
**改法**：`launch_persistent_context(user_data_dir=...)`，见 WS-02。

---

## 7. F 组：变更与回归

### F-24 "三 diff"排查法（昨天能跑今天不行）

按顺序做三个对比，做到哪个断就修哪个：

```
diff① 响应体：把今天的原始响应存下来，和昨天的对比
  - 结构变了 → 改版，走 D-17
  - 变成验证页 → 防护升级，走 C-11
  - 变成空/403 → 走 A 组

diff② 请求参数：抓一次浏览器的手动请求，和你的请求对比
  - 多了参数 → F-26（可能是新签名）
  - 少了 header → B-07
  - URL 变了 → F-25

diff③ 数据内容：同样的请求，条数/字段是否一致
  - 条数少了 → F-27
  - 字段空了 → 权限或登录态
```

**工程建议**：平时就存"基线快照"（第一次成功时的响应样本 + 请求模板）。没有基线，三 diff 无从下手。

### F-25 接口变更
DevTools → Network → Fetch/XHR → 按 Size 排序 → 找返回业务数据的那个。记录：URL、method、必填 header、body 结构。

### F-26 新增必填参数
对比新旧参数集。若新参数值像哈希/时间戳 → 签名，走 WS-07。若是固定常量（如 `appId`）→ 直接补上。

### F-27 数据量变化
```python
print(len(items), resp.json().get("data", {}).get("total"))
```
- `total` 正常但 `items` 少 → 分页 size 变了
- `total` 也少了 → 需要登录 / 需要滚动加载 / 有地区限制

### F-28 第二次跑全空
去重键设计错误（把"同一天同一商品"当成重复）或游标没重置。
**规则**：去重粒度要跟业务语义走（详见 WS-03 第八节的三重去重）。

---

## 8. G 组：工程与系统层

### G-29 内存/进程
```python
try:
    ...
finally:
    ctx.close()          # 必须
    browser.close()
```
+ 启动参数 `--disable-crash-reporter --disable-breakpad`（Docker 里 crashpad 会自重启吃内存）。

### G-30 Docker
```
--no-sandbox --disable-dev-shm-usage --disable-setuid-sandbox
```

### G-31 并发
**并发不是越高越好，是越低越稳。** 顺序：
1. 并发 1，跑 100 条，记录成功率
2. 成功率 100% 再上 2，观察
3. 失败率 >5% 立刻回退
**并发 + 高频 = 最快被封的方式。**

### G-32 卡死
- 每个 `goto` 加 `timeout=30000`
- 每个任务加全局超时（`asyncio.wait_for`）
- 异步流水线收尾要 `await join()`，否则主进程退了子任务还在跑

### G-33 通知假成功
```python
r = requests.post(webhook, json=payload)
if r.status_code == 200:
    body = r.json()
    if body.get("code") not in (0, "0", 200, "ok"):
        raise NotificationError(body)
```
所有 webhook（企业微信 / Bark / Telegram / ntfy / PushPlus）都要**双层判定**。

---

## 9. 判定不了怎么办

如果上面的表都不命中：

1. **降维**：把问题缩到最小 —— 一个 URL、一个 header、一个请求。能复现的最小单元是什么？
2. **对照**：浏览器手动做一次，DevTools 里"Copy as cURL"，直接跑这条 curl。通了说明是你的代码问题；不通说明是环境问题。
3. **二分**：注释掉一半代码再跑。爬虫代码尤其适合二分（尤其是 header 和启动参数）。
4. **记录**：把"证据 + 已排除项"写清楚再去问人。`我已经排除了 IP（换热点仍然失败）、UA（复制浏览器 cURL 成功）、登录（cookie 有效）` 远比 "我的爬虫不工作" 有用。

> 最后一句：**报错信息里永远要带"实际拿到了什么"**。
> `TimeoutError: 选择器未找到` 是无用信息；`TimeoutError: 选择器 .job-card 未找到，实际 HTML 前 500 字：<div id="app"></div>...` 才是可排障的信息。
> 写爬虫时就把这条做进异常里。
