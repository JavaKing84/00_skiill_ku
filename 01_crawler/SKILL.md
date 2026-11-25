---
name: web-scraping-playbook
description: 爬虫与网站数据采集协议库。当用户要求抓取网站数据、采集正文/列表/表格、批量下载网页资源、自动翻页、提取 API/XHR、编写或排查 Playwright/Camoufox 爬虫、分析 403/429/验证码与反爬、登录态采集、断点续采与去重、或寻找并下载图片视频素材时使用。轻量的"读一篇网页/总结文章/普通搜索"不触发。
version: 2.2.0
type: entry
audience: llm-agent
language: zh-CN
library_root: D:/00_skiill_ku/01_crawler
skills_dir: skills/web-scraping
protocol: P0-P5
hard_constraints: 12
triggers: [抓取, 采集, 爬取, 爬虫, 批量下载, 翻页, 反爬, 403, 429, 验证码, XHR, 签名参数, 登录态, 断点续采, 去重, 找素材]
not_triggers: [打开网页, 阅读单篇文章, 总结已有文章, 普通搜索, 网页技术概念解释, 视频剪辑, 技术选型与趋势研究]
executor: D:/00_skiill_ku/03_video/material-sourcing-crawler/scripts/material_crawler.py（库内源；~/.trae-cn/skills 下为安装壳）
browser_runtime: D:/00_skiill_ku/01_crawler/runtime (Playwright + Camoufox；PLAYWRIGHT_BROWSERS_PATH 指向此目录)
browser_ready: 2026-11-19 实测可用 —— playwright SDK 已装（pip install playwright），chromium 直连 D:/00_skiill_ku/01_crawler/runtime/Playwright/chromium-1243/chrome-win64/chrome.exe（chrome 153）验证 200；Camoufox 内核在但 Python SDK 未装
---

# 爬虫执行协议（入口文件）

> 这份文件是**给模型看的**，不是给人看的教程。
> 人类读者请去 [README.md](./README.md)；本文件回答的是「拿到一个爬虫任务，我该按什么顺序做、什么时候停、怎么证明我做成了」。

## 0. 先读这段（30 秒）

你面前是一个**分层技能库**，不是一个代码仓库。你的工作方式必须是：

```
定位任务 → 只加载需要的文件 → 按 P0→P5 推进 → 每阶段过门禁 → 交付带验证
```

三条最容易被忽略的规则：

1. **不要一次读完所有文件**。第 2 节的路由表告诉你读哪几篇。全读约 2000 行，你会把注意力浪费在无关章节上。
2. **不许跳过 P0（情报）直接写代码**。90% 的"爬虫失败"是打错了层——在浏览器指纹上折腾三天，实际数据就在一个 JSON 接口里。
3. **不许没有验证输出就宣称成功**。本库每个阶段都有门禁（gate），门禁不过就退回上一阶段，不要硬着头皮往下走。

> **API 优先原则（2026-11 新增）**：遇到公开数据源（每日新闻、热搜榜单、天气、农历、翻译等），
> 先用 `skills/data/60s-api/scripts/fetch.py` 直取接口，不要直接上浏览器渲染抓取。
> 封装范式见 [skills/data/60s-api/SKILL.md](../skills/data/60s-api/SKILL.md)：
> `requests` + 超时 + 多实例回退 + 字段裁剪，仅依赖标准库与 requests。

---

## 1. 执行协议：六个阶段，五道门禁

| 阶段 | 名称 | 目标 | 交付物 | 门禁（不过就退回） |
|---|---|---|---|---|
| **P0** | 情报 | 搞清楚数据在哪一层 | 目标画像卡 | 能说出"数据来自 DOM / XHR / 独立 API"其中之一 |
| **P1** | 定性 | 确定被什么拦住了 | 分层归因结论 | 有"证据→结论"对，不许猜 |
| **P2** | 选型 | 定技术栈与节奏 | 3 行选型说明 | 能说出为什么不选更简单的方案 |
| **P3** | 打通 | 稳定取到 1 条完整数据 | 可运行脚本 | **连续 3 次**取到同一条数据不失败 |
| **P4** | 工程化 | 变成能长期跑的系统 | 分层项目骨架 | 断网/登出/改版三种异常路径演练通过 |
| **P5** | 交付 | 证明它真的能用 | 验证报告 | 有实际输出，不是"应该可以" |

### P0 情报（10 分钟内完成）

必做的四件事，一件都不能跳：

```bash
# ① 裸 HTTP 看骨架：状态码 + 实际字节数
curl -s -o /dev/null -w "code=%{http_code} bytes=%{size_download}\n" "URL"

# ② 带真实 UA 再试一次（很多人第一步就死在默认 curl UA）
curl -s -o /dev/null -w "code=%{http_code} bytes=%{size_download}\n" \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" \
  "URL"

# ③ 看是不是 SPA 空壳
curl -s "URL" | grep -c "<div id=\"app\"></div>\|<div id=\"root\"></div>"

# ④ 找 XHR：浏览器 DevTools → Network → Fetch/XHR → 刷新 → 按 Size 倒序
```

**浏览器插件协作（2026-11-21 盘点，用户 Chrome 已装）**：
- **Wappalyzer**（技术栈探针）：P0 定渲染层/后端框架时，可请用户在目标页打开 Wappalyzer 面板确认框架/CDN/分析器，比 curl 猜响应头快；结论仍要写进目标画像卡并标注来源是"用户面板确认"。
- **Ghost Downloader**（多线程下载加速）：P4/P5 阶段大文件（视频素材、数据集）脚本下载慢时，可把直链交给用户用 Ghost Downloader 手动加速，落盘后仍按本库清单契约补 SHA256 与 PIL/ffprobe 验证。
- **Immersive Translate**：外文情报正文检索时无需依赖——模型直接读英文原文即可，插件只作人工浏览辅助，不进采集链路。
- 其余（Adblock/DuckDuckGo/Peek Pop/boss-helper）与采集链路无关，不吸纳。

**产出「目标画像卡」**（写进你的回复里，不要只在脑子里）：

```
站点：xxx
渲染层：SSR / SPA / 接口化
数据位置：DOM 选择器 / XHR JSON 接口（URL: ...）/ 独立开放 API
需登录：是（凭据类型：cookie / token / 扫码）/ 否
签名参数：无 / 有（参数名：sign、_m_h5_tk ...）
已知防护：无 / Cloudflare / 自研风控 / CDP 检测
```

> **P0 的最高价值判断**：如果数据在 XHR 里返回 JSON，**立刻放弃浏览器方案**，直接构造请求。
> 只有当接口带无法复现的签名（→ 07 号文档），或者数据只存在于 DOM（服务端不吐 JSON），才需要上浏览器。

### P1 定性（关键：分层，不要猜）

按成本和概率排序查，**每次只改一个变量**：

```
① 同机手工打开浏览器能不能正常访问？
   └─ 不能 → IP 层封禁。停下所有代码优化，先换出口（家宽重拨/热点/自建池）
② 裸 curl 拿到啥？
   ├─ 403 + server: cloudflare / cf-ray → WAF 指纹层（→ 01 第三节）
   ├─ 200 但只有几 KB + <div id="app"> → SPA，去 P0 找 XHR
   ├─ 200 但正文是验证页/滑块 → 行为风控（→ 01 第三节）
   └─ 302 → 登录墙（→ 03 第五节 登录态复用）
③ 上了真内核浏览器还是空？
   ├─ url 变 about:blank / body_len 0~15 → CDP 级检测（→ 02 全文）
   └─ 页面正常但点一下就跳验证 → 行为风控（→ 03 第六节 拟人节奏）
④ 数据拿到了但字段不对/被改/是假数据？
   └─ 字体混淆 / 假数据投毒 / 字段加密（→ 05 号 症状 F-11 起）
⑤ 接口要求 sign/token/时间戳签名？
   └─ → 07 号文档（签名逆向）
```

**门禁**：你的结论必须写成 `证据 → 结论` 的形式，例如
`code=200 bytes=1832 html 含 <div id="app"> → SPA 空壳，数据在 XHR`。
只写"应该是反爬"不通过。

### P2 选型

| 定性结论 | 武器 | 参考 |
|---|---|---|
| 无防护 / 弱防护 | `httpx` / `requests` 直连 | — |
| SPA 但接口干净 | 抓接口 + 直连（**不要上浏览器**） | P0 |
| 常规指纹校验 | Playwright + stealth | 01 §三 |
| 深度指纹（CF/Akamai） | Camoufox（Firefox 基底） | 01 §三 |
| CDP 级检测 | patchright + persistent context | **02 全文** |
| 签名参数 | 浏览器内执行 / 扣代码补环境 | **07 全文** |
| 需登录 + 长期跑 | 持久化 profile + 账号池 + 熔断 | 03 §五 §三 §四 |
| 多源、低频、要对外供数 | 离线抓取 + 静态快照 + 只读 API | **04 全文** |

**门禁**：必须能回答"为什么不用更简单的那个"。答不出来说明 P0/P1 没做透。

**本机现成的浏览器调用（2026-11-19 实测可用，PG-01）**：内核与 SDK 已就位，直接按绝对路径启动，**不要跑 `playwright install`**（会重下几百 MB）：

```python
from playwright.sync_api import sync_playwright
EXE = r"D:\00_skiill_ku\01_crawler\runtime\Playwright\chromium-1243\chrome-win64\chrome.exe"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE, headless=True,
                          args=["--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(user_agent="Mozilla/5.0 ... Chrome/153.0.0.0 Safari/537.36", locale="en-US")
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    pg = ctx.new_page(); pg.goto(url, wait_until="domcontentloaded", timeout=35000)
```

已用它打通的实例：BleepingComputer 的 Cloudflare 托管挑战（curl_cffi 与代理均 403，浏览器 200 取到 RSS）。
**打不通的**：The Record（CF「Just a moment」，无头等 16s 挑战不自过）、Packet Storm（TOS 同意页按钮被 CSS 隐藏）——
这两类要 `headless=False` 或 Camoufox，别在无头里死磕。

### P3 打通（只做一条数据）

规则：
- **单线程、单页、不并发、不去重、不落库**。先把一条数据完整取到。
- 取到的定义：**目标字段全部非空且语义正确**（不是"元素找到了"，是"取出来的值对"）。
- **连续跑 3 次**，3 次都拿到。1 次成功 2 次失败 = 没打通，是运气。

### P4 工程化

两条路线，按目标选一条，不要混：

```
路线 A（单站深挖、要实时盯、要长期跑）
   → 03 号全文。重点抄：分层骨架 / 熔断 / 轮换 / 三重去重 / 拟人节奏表

路线 B（多源聚合、低频更新、要对外供数）
   → 04 号全文。重点抄：离线抓取+快照 / encoding 多形态 / 统一契约
```

**门禁**：三种异常必须演练并给出预期行为：

| 异常 | 期望行为 |
|---|---|
| 断网 / 代理挂 | 重试有限次 → 换节点 → 仍失败则记录并退出，不空转 |
| 登录失效 | 抛专用异常 → 不重试 → 通知人工 → 更新凭据后自动恢复 |
| 目标改版（选择器全失效） | 报错信息里带**实际拿到的 HTML 片段**，而不是 `TimeoutError` |

### P5 交付

交付物必须包含五段，缺一段视为未完成：

```
1. 定性结论   证据 → 结论
2. 技术选型   为什么是它，不是别的
3. 可运行代码 能直接跑，路径/依赖写清
4. 验证方式   命令 + 期望输出（不是"应该能跑"）
5. 风险与边界 什么情况下会挂，挂了怎么办
```

---

## 2. 路由表（只读需要的）

| 你遇到的情况 | 主读 | 辅读 |
|---|---|---|
| 完全不知道从哪下手 | 本文件 §1 | 01 |
| 403 / 503 / 验证码 / 被拦 | **01** | 02、05 |
| 状态 200 但页面空、`about:blank` | **02** | 05 |
| 要建一个能长期跑的系统 | **03** | 06 |
| 多数据源、要对外提供 API | **04** | 06 |
| 接口有 sign / token / 加密参数 | **07** | 05 |
| 昨天能跑今天挂了 | **05**（查表） | 对应主文档 |
| 要抄现成代码 | **06** | — |
| 想系统补课 | README 学习路径 | — |

**文件清单**

| ID | 文件 | 定位 | 约 |
|---|---|---|---|
| — | `SKILL.md`（本文件） | 协议与路由 | 1.2k |
| WS-01 | `01_anti_scraping_sop.md` | 反爬侦察通用 SOP | 1.8k |
| WS-02 | `02_cdp_detection_bypass.md` | CDP 级检测破局实战 | 2.2k |
| WS-03 | `03_deep_site_scraper_engineering.md` | 单站深挖系统工程化 | 5k |
| WS-04 | `04_aggregator_pipeline_design.md` | 采集/服务解耦架构 | 3k |
| WS-05 | `05_failure_taxonomy.md` | 症状→根因→动作 查表 | 3k |
| WS-06 | `06_code_templates.md` | 可运行代码模板 | 4k |
| WS-07 | `07_js_signature_reverse.md` | 签名参数逆向 | 3k |

---

## 3. 术语归一（用户黑话 → 工程任务）

用户不会说"我被 Cloudflare 拦了"，他会说这些。**直接映射成任务，不要反问，不要解释术语**：

| 用户说法 | 真实任务 |
|---|---|
| 拿不到数据 / 抓下来是空的 | P0：先判断数据在哪一层 |
| 被封了 / 被限制了 / 一直报错 | P1：分层归因 |
| 白屏 / 页面不加载 / 一直转圈 | 05 号 F-03/F-04（多半是 CDP 或 header 污染） |
| 有验证码 / 滑块 / 要人机验证 | 05 号 F-06（行为风控） |
| 昨天好好的今天不行了 | 05 号 F-20 起（改版 / 凭据过期 / 防护升级） |
| 要登录 / 要 cookie | 03 §五（登录态复用 + 托管头黑名单） |
| 有加密 / 有签名 / 参数看不懂 | 07 全文 |
| 太慢了 / 要并发 | 03 §六（先降频再谈并发，顺序不能反） |
| 要定时跑 / 要一直盯着 | 03 §十二（cron）或 04（多源周期） |
| 抓完要给别人用 | 04（只读 API + encoding 多形态） |
| 数据不对 / 数字全是乱的 | 05 号 F-11 起（字体混淆 / 假数据） |

---

## 4. 硬约束（违反任何一条，这次任务就算失败）

| # | 约束 | 原因 |
|---|---|---|
| C1 | 不做 P0 不写代码 | 打错层是最贵的错误 |
| C2 | 不用固定 `sleep` | 固定间隔本身就是风控特征（03 §6.4） |
| C3 | 不写死 CSS 类名哈希 | `[class*='xxx']` 优先，哈希会随构建变（03 §七） |
| C4 | 报错后不加 stealth 库 | 先定性。stealth 对 CDP 层无效（02 §三） |
| C5 | 不把"绕过检测"当成"可以高频" | 节奏控制优先于任何指纹补丁 |
| C6 | 不声称成功而无输出 | 必须有实际命令输出 / 数据样本 |
| C7 | 不把模型生成的选择器、哈希、偏移当作已验证事实 | 必须实跑一次，报错就改 |
| C8 | 不接商业打码 / 付费代理 | 本库立场：降频 + 自建池 + 开源方案优先 |
| C9 | 不越合规边界 | 只抓有权访问的数据；遵守 robots 与服务条款；控制频率不造成负担 |
| C10 | 不提取第三方代理/客户端的加密凭据来换取控制权 | 代理软件的 secret 属于其自身访问控制；需要切换策略时由用户在 UI 操作，脚本只探测「端口是否可用」 |
| C11 | 不用 `taskkill /F /IM chrome.exe` 清理浏览器 | 会误杀用户在用会话（投递/办公）；必须按专用 `--user-data-dir` 或 PID 精确匹配 |
| C12 | 不把「换 IP」当作 403 的第一反应 | 先做速率判别（见 §9.4）；无脑轮换节点会把限流打成 IP 级封禁 |

> C7 特别重要：**你（模型）最容易犯的错是编造一个看起来合理的 CSS 选择器**。
> 正确做法是先把候选选择器的**计数**打出来验证（`locator(sel).count()`），count>0 才算存在。

---

## 5. 每次回复的最小结构

```
【定性】证据 → 结论
【动作】这一步要做什么，为什么
【代码】可直接运行
【验证】命令 + 期望输出
【下一步】若失败去哪查（给文档编号 + 症状编号）
```

中间过程可以省略，这五段不能省。**用户要的是能跑的东西，不是分析报告。**

---

## 6. 上下文预算建议

| 情况 | 建议加载 |
|---|---|
| 快速问答 | 只读本文件 §2 §3 |
| 单个报错排障 | 本文件 §1 P1 + **05**（查表，别读全文） |
| 写一个新爬虫 | 本文件全部 + **01** + **06** |
| 硬骨头（CDP / 签名） | 本文件 + **02** 或 **07** + **06** |
| 做系统 | 本文件 + **03**（A 路线）或 **04**（B 路线） |

**信任度声明**：本库中的参数（延迟秒数、阈值、TTL）是**经验起点**，不是定理。落地时要按目标站点的实际响应调整，并在代码里做成可配置项，不要硬编码。

---

## 7. 职责边界与执行入口（2026-11-17 补充）

### 7.1 谁负责什么

| 角色 | 实体 | 职责 |
|---|---|---|
| 协议库（本文件 + WS-01～08） | `D:\00_skiill_ku\01_crawler` | 怎么定性、怎么选型、怎么排障、怎么收敛；**不负责实际下载** |
| 执行器 | `~\.trae-cn\skills\material-sourcing-crawler\scripts\material_crawler.py` | 真正请求、落盘、生成 manifest；被客户端直接调用 |
| 共享底座 | `D:\00_skiill_ku\_shared\skillkit\{policy,manifest,hashing,loggingx}.py` | 限速/退避/断点/两级去重/脱敏日志，被采集器与情报系统共同复用 |

**不要另建第二套采集 runner**：本目录的 `scripts\` 只放探测 / 抽取 / 矩阵工具（P0 情报层与正文抽取），
不承担“下载执行器”；真实请求、落盘与 manifest 由 `material_crawler.py` 负责。
需要新能力时，在执行器内按 WS-06 模板扩展，并复用 `_shared/skillkit` 的策略与清单模块。

### 7.2 执行入口

```powershell
# 素材/网页采集（真实执行器）
python ~\Users\<user>\.trae-cn\skills\material-sourcing-crawler\scripts\material_crawler.py `
  --q "<关键词>" --videos 3 --images 2 --orientation portrait --out "<输出目录>" --json
# 产出 manifest.json：核对条数、字段、落盘文件是否可解码
```

### 7.3 轻量 vs 完整流程

- 轻量（单页、少量条目、无反爬迹象）：直接请求 → 校验 → 落盘 → 计数，不启动 P0–P5 全流程。
- 完整（403/429/验证码/登录态/签名参数/多站点）：按 §1 的 P0→P5 推进，逐段过门禁。

### 7.4 输出与验收

每次采集必须交付：① 数据条数与字段完整度；② 落盘路径与校验结果（SHA256 / 大小 / 可解码）；
③ 去重结果（新增 vs 重复）；④ 失败项与失败码（查 `05_failure_taxonomy.md`）；
⑤ 来源 URL 与采集时间。只给方案或只给脚本，不算完成。

### 7.5 统一元数据契约

采集结果字段、许可标注（默认 `unknown`）、重试上限、断点、去重规则见
`skills/web-scraping/08_unified_collection_contract.md`；采集结果若需长期沉淀为技术情报，
使用同一 `assets_manifest.json`（material 适配器）并转 TechRadar 入库，保留原始来源溯源。

---

## 8. 工具层（2026-11-18 新增，均已实测）

| 工具 | 路径 | 作用 | 实测状态 |
|---|---|---|---|
| `probe_site.py` | `scripts/probe_site.py` | 单次公开探测：状态码/渲染层/结构化数据/媒体线索/阻断词 | PASS（8 目标） |
| `probe_logged_in.py` | `scripts/probe_logged_in.py` | **用户授权范围内**的登录态页面判定；不读取/导出凭据；遇验证码即停 | PASS（3 平台，2 个触发风控即停） |
| `extract_article.py` | `scripts/extract_article.py` | 正文抽取三引擎：trafilatura → readability → 内置兜底 | PASS（3 站点基准） |
| `build_platform_matrix.py` | `scripts/build_platform_matrix.py` | 汇总探测产物为兼容矩阵（JSON + MD） | PASS（11 行） |

### 8.1 平台基线（实测，详见 `reports/platform_matrix.md`）

| 平台 | 公开可达 | 数据结构 | 结论 |
|---|---|---|---|
| Bilibili | 是 | 公开 API `x/web-interface/popular` code=0 | **可直接采集**（视频详情/热门） |
| Douyin | 页面 200 | 热榜接口返回非 JSON（需签名） | 页面可访问，接口需签名；登录态触发风控 |
| 小红书 | 是 | SPA 壳（`__INITIAL_STATE__`） | 需 JS 渲染；登录态触发风控 |
| YouTube | 是 | SSR | 页面可读；播放地址需解析 player 响应 |
| 通用文章站 | 是 | SSR + JSON-LD | 抽取链路可用 |
| Reddit | 否（403） | 需 OAuth | 必须走官方授权，禁止绕过 |

### 8.2 登录态采集规则（用户已授权，但有硬边界）

- 只复用**用户本机**已登录的浏览器 `user-data-dir`；不读取、不打印、不导出 Cookie / localStorage / 密码。
- 遇到验证码、人机验证、短信/人脸二次验证：**立即停止并记录 BLOCKED**，不尝试任何绕过。
- 不轮换账号、不规避限流、不伪造 UA 规避风控。
- 若探测结果显示 `LOGGED_OUT` 或 `BLOCKED_CHALLENGE`，如实报告，不把"页面能打开"说成"已登录可采"。

### 8.3 技术采纳结论（依据真实审计，非热度）

| 候选 | 结论 | 理由 |
|---|---|---|
| trafilatura | **采纳（可选依赖）** | 三站点基准中抽取最干净；缺失时自动降级 |
| readability-lxml | **采纳为降级** | 部分站点可用；github.blog 上失效 |
| Scrapling | **暂缓** | 体量大、与既有 Playwright 运行时重叠 |
| Crawl4AI | **暂缓** | 依赖较重，当前轻量流程不需要 LLM 抽取 |
| browser-use | **暂缓** | Agent 浏览器编排，超出采集层职责 |
| Crawlee-Python | **参考** | 队列/重试模型可借鉴，不整体引入 |
| firecrawl | **不引入** | AGPL-3.0 + 服务化依赖，与本地优先冲突 |
| MagicalMirror | **拒绝** | 实测 1 star、2020 年停更，不可用 |

### 8.4 抽取消歧

- `trafilatura` 未安装时不要报错退出，走 `readability` → 内置兜底，并在输出里标明实际引擎。
- 正文 <200 字符视为抽取失败（返回码 1），不得把空壳当成功。

---

## 9. 实战沉淀：403 判别与浏览器降级（2026-11-24 Reddit 案例）

> 本节全部来自一次真实攻坚：Reddit 采集先成功、4 分钟后全端点 403。
> 标注「实测」的有命令/mtime 证据；标注「经验」的是通用结论、未在本机分离变量验证。

### 9.1 指纹 ≠ IP：`curl_cffi` 的能力边界

| 层 | `curl_cffi(impersonate="chrome")` | 结论 |
|---|---|---|
| TLS/JA3 指纹 | 可伪装 | 有效 |
| HTTP/2 帧序、header 顺序 | 可伪装 | 有效 |
| ASN / 出口 IP 信誉 | **改不了** | 无效 |
| 高频行为模式 | **改不了** | 无效 |

实测：同一出口用 `impersonate="chrome"` 打 `reddit.com` 全端点，仍返回同一张 190KB 拦截页。
**判定规则**：换指纹后状态码不变 → 说明拦截在 IP 层或行为层，继续换指纹是浪费时间。

### 9.2 无头与离屏窗口：检测面不同

- `--headless=new` 会暴露 `HeadlessChrome` UA 片段、缺失的 GPU/音频栈、异常 `navigator.plugins` 等特征，高级风控（Cloudflare、Reddit、DataDome）可稳定识别。
- 离屏真实窗口 `--window-position=-32000,-32000 --window-size=1440,900` 保留完整渲染栈，检测面与普通窗口一致，代价是需要交互桌面（SYSTEM 服务/无会话环境下不可用）。

> 经验结论，本机未分离验证：本次 403 属 IP 层，两种模式结果相同，无法据此比较检测率。
> 执行边界：该参数用于「自己被授权访问的站点」的稳定性，不是绕过付费墙/登录墙的手段；节奏控制（C5）永远优先于指纹伪装。

### 9.3 接口降级链（JSON → HTML → DOM）

```
① 公开 JSON 接口（/new.json、/api/...）
   ├─ 200 → 直接解析
   └─ 403/429 → ②（不要立刻重试同一接口）
② 真实浏览器加载 HTML 列表页
   ├─ 200 但内容是 SPA 空壳 → 等渲染或换 XHR（回 ①）
   ├─ 200 且有服务端渲染节点（Reddit: <shreddit-post>）→ 提取 DOM 属性
   └─ 403 → ③
③ 官方替代通道（RSS / OAuth / 第三方聚合）
   └─ 都不可用 → 标记 BLOCKED，不伪造数据
```

Reddit 的 DOM 字段映射（实测可用）：`post-title`、`permalink`、`created-timestamp`、`author`、`score`、`comment-count`。

### 9.4 403 判别树（最重要的一条）

```
先问：同一出口、同一 UA，最近是否成功过？
├─ 是（先 200 后 403）
│   → 速率/行为封禁。动作：停止请求，冷却 ≥6h；恢复时单线程、单页面、
│     请求间隔 25–45s、失败不立即重试（指数退避 2/4/8 分钟）
└─ 否（一直 403）
    → 才可能是 IP/ASN 封禁。此时换出口才有意义
```

实测证据（本地时间 2026-11-24）：

| 时间 | 事件 |
|---|---|
| 18:32:58 | 4 个 sub × 2 页连续请求，40 条入库成功 |
| 18:32:59 | 源状态被写入 `站点按出口 IP 返回 403` |
| 18:36:14 | 之后 `.json` / HTML / `old.` / `api.` / `oauth.` 全部 403 |

**换节点会怎样**：等于换一个 IP 再打一遍同样的 8 连发，4 分钟后得到同样的 403。轮换只能把「限流」升级成「IP 级封禁」，不解决问题。

### 9.5 工程红线

见 §4 的 C10–C12：不提取代理软件凭据、不 `taskkill /IM`、不把换 IP 当第一反应。

### 9.6 平台策略变更要先查，再写代码

Reddit 已公告：RSS 于 2026-11-13 停服，新 API 申请 2026-10-31 停止受理，公共 Data API 2027-03 关闭。
**教训**：动手前先确认目标平台当前是否还有合法自动化入口；政策已关闭时，正确动作是改架构（换聚合源/换数据商），不是加强对抗。

---

## 10. 脚本参数参考（2026-11-24 同步）

本目录 `scripts\` 下 4 个工具的完整参数以 [CLI_REFERENCE.md](./CLI_REFERENCE.md) 为准
（由 argparse 自动提取，改脚本后重新生成）。常用命令：

```powershell
$PY = "D:\00_skiill_ku\.venv\Scripts\python.exe"

# P0 探测：状态码 / 渲染层 / 结构化数据 / 媒体线索
& $PY D:\00_skiill_ku\01_crawler\scripts\probe_site.py --url "https://example.com" --out probe.json
& $PY D:\00_skiill_ku\01_crawler\scripts\probe_site.py --url "https://example.com/api" --api

# 登录态可访问性探测（不读取/导出凭据；遇验证码即停）
& $PY D:\00_skiill_ku\01_crawler\scripts\probe_logged_in.py --site "https://example.com" --profile "<user-data-dir>"

# 正文抽取三引擎（auto → trafilatura → readability → builtin）
& $PY D:\00_skiill_ku\01_crawler\scripts\extract_article.py --url "https://example.com/post" --engine auto --out body.md

# 汇总探测结果为平台兼容矩阵
& $PY D:\00_skiill_ku\01_crawler\scripts\build_platform_matrix.py --in-dir .\reports
```

> 真实采集/下载请走执行器：
> `python ~\.trae-cn\skills\material-sourcing-crawler\scripts\material_crawler.py ...`（库内源在 `03_video\material-sourcing-crawler`）。
> 本目录脚本只做探测与抽取，不生成 `assets_manifest.json`。
