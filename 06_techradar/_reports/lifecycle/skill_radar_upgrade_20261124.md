# TechRadar 与爬虫 Skill 升级报告

- 日期：2026-11-24
- 范围：`D:\00_skiill_ku\01_crawler`（协议库）+ `D:\00_skiill_ku\06_techradar`（情报库）
- 依据：本轮 Reddit 403 攻坚的实测证据（见 `ultimate_fix.md` 第 8 节）

---

## 1. 变更总览

| 层 | 文件 | 变更 |
|---|---|---|
| 协议库 | `01_crawler/SKILL.md` | 版本 2.1.0 → **2.2.0**；新增 §9 实战沉淀；硬约束 9 → **12**（新增 C10/C11/C12） |
| 协议库 | `06_techradar/scripts/websession.py` | `_kill_pids` 增加 C11 红线注释（禁止全局杀 Chrome） |
| 协议库 | `06_techradar/scripts/collect_reddit.py` | `WebSessionBlocked` 分支增加 §9.4 判别注释（先 200 后 403 = 速率封禁） |
| 情报系统 | `06_techradar/scripts/public_sources.py` | 新增 2 个排障源；新增代码块抽取；新增 4 类技术语境标签 |
| 情报系统 | `06_techradar/scripts/ingest_case_notes.py` | 新增，案例条目入库脚本（可重复执行，按 URL+标题去重） |
| 情报库 | `techradar.db` | 写入 3 条 `knowledge_base` 条目 |

---

## 2. 爬虫 Skill 新增了什么规则

### 2.1 新增 §9「实战沉淀：403 判别与浏览器降级」

| 小节 | 规则 | 证据等级 |
|---|---|---|
| 9.1 | `curl_cffi(impersonate="chrome")` 只能伪装 TLS/JA3、HTTP2 帧序、header 顺序；**改不了 ASN/IP 信誉与高频行为模式**。换指纹后状态码不变 → 拦截不在指纹层 | 实测（同一出口换 impersonate 后仍 403） |
| 9.2 | `--headless=new` 暴露 HeadlessChrome 片段/缺失 GPU 栈等特征，高级风控可识别；离屏真实窗口 `--window-position=-32000,-32000 --window-size=1440,900` 检测面接近普通窗口，但需要交互桌面 | 经验（本机 403 属 IP 层，两种模式结果相同，未分离验证，已在文中标注） |
| 9.3 | 接口降级链：JSON 403 → 真实浏览器 HTML → DOM 提取 → 官方通道 → BLOCKED。附 Reddit `shreddit-post` 字段映射 | 实测 |
| 9.4 | **403 判别树**：同出口先 200 后 403 = 速率/行为封禁 → 冷却 ≥6h、单线程单页、间隔 25–45s、指数退避；持续 403 才判定 IP 封禁。换节点只会把限流升级成 IP 级封禁 | 实测（18:32 成功 → 18:36 全 403） |
| 9.5 | 引用 C10–C12 | — |
| 9.6 | 动手前先确认平台是否还有合法自动化入口；政策关闭时改架构而不是加强对抗 | 实测（Reddit RSS 停服/API 停申） |

### 2.2 新增硬约束

| 编号 | 约束 |
|---|---|
| C10 | 不提取第三方代理/客户端的加密凭据来换取控制权；切换策略由用户在 UI 操作，脚本只探测端口可用性 |
| C11 | 不用 `taskkill /F /IM chrome.exe`；必须按专用 `--user-data-dir` 或 PID 精确匹配 |
| C12 | 不把「换 IP」当作 403 的第一反应；先做速率判别 |

---

## 3. 雷达库优化了哪些源和标签

### 3.1 新增采集源（`public_sources.py`，规格数 13 → 15）

| source_id | 名称 | 实现 |
|---|---|---|
| `github_issues` | GitHub Issues 排障检索 | 4 组报错特征查询（`403 in:title cloudflare`、`playwright in:title blocked`、`curl_cffi in:title 403`、`reddit in:title blocked 403`），`is:issue` + relevance 排序，过滤 PR |
| `stackoverflow` | Stack Overflow 排障问答 | StackExchange 公开 API，tag：`web-scraping` / `playwright` / `python-requests`，`filter=withbody` 取正文 |

实测：`github_issues` 4 条（Cloudflare 403 相关 issue），`stackoverflow` 6 条（其中 5 条带代码块）。

**关于 r/webscraping**：无法直连（本机出口对 reddit.com 全端点 403），已在代码注释中标注——必须先在 Folo 客户端订阅该 subreddit，再由 `collect_folo.py` 入库。未强行接入一个每轮必然失败的源。

### 3.2 代码块抽取

- 新增 `_extract_code_blocks()`：正则匹配 `<pre><code>` 与 `<pre>`，去标签后**保留原始缩进与换行**，单块上限 4000 字符、单条上限 5 块，<20 字符的片段丢弃。
- 接入点：`parse_feed()`（RSS/Atom 两种分支）+ `github_issues` + `stackoverflow`，统一落到 `entries.extra_json.code_blocks`。
- 未新增数据库列：`extra_json` 已是项目约定的扩展字段，加列需要迁移，收益不值当。

### 3.3 新增技术语境标签

命中关键词自动打标（写入 `entry_tags`，可在 `radar_query --tag` 直接过滤）：

| 标签 | 触发关键词（节选） |
|---|---|
| `anti-bot` | 403 / 429 / cloudflare / captcha / waf / rate limit / bot detection / 反爬 / 封禁 / 风控 |
| `browser-automation` | playwright / selenium / puppeteer / headless / cdp / browser automation / chromium |
| `api-change` | deprecated / breaking change / sunset / eol / api shutdown / no longer / stopped accepting / 停服 / 下线 / 关闭 |
| `engineering-decision` | trade-off / architecture / migration / 替代方案 / 取舍 / 架构 / 选型 / 决策 |

---

## 4. 写入了哪 3 条知识图谱

| 标题 | category | 标签 | 关联 URL |
|---|---|---|---|
| 【实战】Reddit 403 判别：先 200 后 403 属速率封禁，DOM 降级与离屏浏览器参数 | anti-bot | case-study, anti-bot, browser-automation, reddit, 403 | `reddit.com/r/LocalLLaMA/new.json` |
| 【架构决策】Reddit RSS 停服后的替代路径：Folo 聚合中转，而非加强反爬对抗 | engineering-decision | case-study, engineering-decision, api-change, reddit, folo | Reddit 停服报道原链 |
| 【工程规范】本地代理探测（204 校验）、Playwright 代理注入与浏览器进程精准管理 | engineering-decision | case-study, engineering-decision, browser-automation, proxy, windows | Playwright 官方 API 文档 |

入库结果：

```
knowledge_base status=READY fetched=3 inserted=3 dedup=0 quarantined=0 error=None
```

写入前先在副本 `%TEMP%\techradar_copy.db` 验证，确认 3 条全部入库、0 条被 provenance 校验隔离，再写正式库。

**库内已有**：`knowledge_base` 下另有 3 条 18:48 由前序流程写入的条目（Playwright 反爬、curl_cffi 指纹、Reddit DOM 降级），本次未覆盖，按 URL+标题哈希共存。

---

## 5. 闭环验证

```powershell
python radar_query.py --db D:\00_skiill_ku\06_techradar\data\techradar.db --text "离屏浏览器绕过 403" --limit 5
```

```
自定义检索: hits=5 engine=fts5 fts=fts_available
  [troubleshooting] Playwright/Chrome 反爬实战：--headless=new 易被识别…  | knowledge_base | 2026-11-24T18:48:30
  [troubleshooting] curl_cffi TLS 指纹伪装…                          | knowledge_base | 2026-11-24T18:48:30
  [troubleshooting] Reddit 反爬判别：JSON 接口 403…                   | knowledge_base | 2026-11-24T18:48:30
  [anti-bot]     【实战】Reddit 403 判别…                            | knowledge_base | 2026-11-24T10:40:00Z
  [engineering-decision] 【工程规范】本地代理探测…                     | knowledge_base | 2026-11-24T10:40:00Z
```

**Hit = True**（5 条，全部来自 `knowledge_base`，前 3 条为既有条目，后 2 条为本次新增）。

命中机制说明：`radar_query` 的 `TECH_SOURCE_PRIORITY` 首位就是 `knowledge_base`，所以技术类查询会先查知识库；中文走 FTS5 前缀匹配 + CJK 零命中自动降级 LIKE 兜底，本次未触发降级（`engine=fts5`）。

---

## 6. 边界与未做项

1. **未改数据库结构**：代码块存入 `extra_json.code_blocks`，未加列；需要独立列做 SQL 聚合时再迁移。
2. **未接入 r/webscraping 直采**：出口被封，走 Folo 订阅路径，代码层不新增必然失败的源。
3. **未把 §9.2 写成"已验证"**：无头 vs 离屏的检测率差异在本机无法分离验证（403 发生在 IP 层），文中已显式标注为经验结论。
4. **新增源会增加单轮耗时**：`github_issues` 4 次 + `stackoverflow` 3 次请求，均为公开 API；GitHub search 未认证限额 10 次/分钟，单查询失败只丢该查询，不影响整轮。
5. **`ingest_case_notes.py` 可重复执行**：靠 `content_hash = hash(URL+标题)` 去重，重复运行只会 dedup，不会产生重复条目。
