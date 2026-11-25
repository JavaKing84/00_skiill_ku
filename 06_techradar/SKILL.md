---
name: techradar-canonical
description: TechRadar 技术情报系统 canonical 技能（健康检查→分层阅读→证据入库→跨领域组合→可验证行动），含 SQLite 情报库、公开源降级链、二级聚合源「资源雷达」、情报价值动态评分与数据库生命周期/定时任务强制能力；跨客户端可迁移、可持续自维护。
version: 1.4.0
language: zh-CN
triggers: [技术选型, 开源项目, 技术趋势, 新模型, 新框架, 情报, 订阅源, 收录, 情报库, 上周收集, 跨领域研究, 持续跟踪]
not_triggers: [普通报错修复, 基础概念解释, 普通翻译写作, 单篇文档总结, 网页打开, 视频剪辑, 素材采集]
execution_entry: D:/00_skiill_ku/06_techradar/scripts (radar_query / collect_public / collect_zcl / lifecycle_run / scheduler)
db: D:/00_skiill_ku/06_techradar/data/techradar.db
---

# TechRadar 技术情报系统（Canonical）

> 与 Trae 内 `~\.trae-cn\skills\tech-radar\SKILL.md` 的关系：那份是会话触发版（模式 A–D 路由），
> 本文件是**带本地数据库、可执行脚本、定时任务与生命周期治理的工程版**，两份的模式 A 协议（A0–A7）保持一致。
> 文档同步：2026-11-24（radar v2，`scripts\` 实际 23 个 .py；参数以 [CLI_REFERENCE.md](./CLI_REFERENCE.md) 为准）。

## 0. 启动自检（每次加载 Skill 必须执行，幂等，不可跳过）

任何 Agent 首次加载本 Skill 或新会话开始处理情报任务前，按顺序检查并在回答里给出一行状态：

```powershell
# ① 数据库与表结构是否存在（应含 entries/sources/job_runs/purge_log/task_registry）
python 06_techradar/scripts/scheduler.py --action status

# ② 若任务缺失 → 安装（已存在则 EXISTS_OK，不会重复创建）
python 06_techradar/scripts/scheduler.py --action install
```

判定规则：
- 数据库缺失 → 先执行 `IntelDB` 初始化（会自动建表并迁移到最新 schema）。
- 注册表 `06_techradar/data/TASK_REGISTRY.json` 缺失或 `skill_version` 低于当前 Skill → 执行 `install` 同步任务，**不新建重复任务**。
- 四个任务全部 `EXISTS_OK`/`CREATED` → 只做健康巡检，不再重复安装。
- 非 Windows 或环境不支持后台任务 → 明确报 `BLOCKED`，给出可手动执行的等义命令，**禁止声称已创建成功**。

## 1. 工作流（每次情报任务固定顺序）

1. **健康检查**：`python 06_techradar/scripts/healthcheck.py --out _reports/health_<ts>.json
   --mcp-folo <ok|auth_required|...> --mcp-reddit <...>`（MCP 实测结果由会话工具获得后传入）。
2. **分层阅读**：标题扫描 → 正文读取 → 评论精读 → 仓库/论文深挖，四级数量分别记账，不许合并虚报。
3. **证据入库**：所有条目经 `IntelDB.add_entry` 写入 SQLite，`content_hash` 唯一约束自动去重。
4. **分析组合**：跨领域组合必须给组件职责、数据流、最小验证、风险与证据链接，不堆名词。
5. **报告输出**：状态条 + 覆盖率台账 + ≤5 条发现（六段式）+ 破圈新源 + 零命中声明。

## 2. 数据源分级与降级链

| 级别 | 源 | 接入方式 | 当前状态（2026-11-19） |
|---|---|---|---|
| S1 用户订阅 | Folo（LINUX DO、GitHub Trending、吾爱破解等 6 源） | folo MCP | BLOCKED: 缺 FOLO_SESSION_TOKEN |
| S1 用户订阅 | Reddit（r/coolgithubprojects 等 3 社区 + 安全社区 r/netsec、r/cybersecurity、r/ReverseEngineering、r/hacking、r/Malware） | reddit MCP | BLOCKED: 匿名 RSS 已关，缺 API 凭据 |
| S1.5 二级聚合 | **资源雷达 radar.zichuanlan.top**（112 源/80 启用，上游含 LINUX DO、NodeSeek、V2EX、Telegram、知乎/小红书回环、GitHub README 清单等） | `collect_zcl.py` 走公开只读 API，无需鉴权 | PASS（2026-11-17 实测，80 条入库） |
| S2 公开替代 | Hacker News / GitHub Search | `collect_public.py`（无需登录） | PASS |
| **S2 安全情报** | **黑客/安全媒体 12 站（The Hacker News、Krebs、Dark Reading、HackRead、CyberScoop、Cybersecurity Dive、Securelist、PortSwigger Research、Seclists Full Disclosure、先知社区、Infosecurity Magazine、Security Affairs）** | `sec_rss` 适配器（`collect_public_suite.py --only sec_rss`） | PASS（2026-11-19 实测，首轮 50 条入库，重跑 0 新增 50 去重） |
| **S2 漏洞证据** | **GitHub Security Advisories（GHSA/CVE/CVSS）** | `github_advisories`（GitHub 公开 API，零凭证） | PASS（2026-11-19 实测，10 条入库） |
| **S2 在野利用** | **CISA KEV 已知被利用漏洞目录** | `cisa_kev`（公开 JSON，按 dateAdded 倒序） | PASS（2026-11-19 实测，5 条入库） |
| **S2 受限安全** | **Exploit-DB（已解）、SecurityWeek（需代理）、BleepingComputer（已解，浏览器通道）、The Record / Packet Storm（未解）** | `sec_restricted` 三级回退（curl_cffi 指纹 → 代理 → 无头浏览器 → 跳过） | PASS（2026-11-19 实测：16 条 / 10.6s，通道 impersonate 8 + browser 8） |
| S3 兜底 | WebSearch + 爬虫库 Playwright/Camoufox | 会话工具 + WS-01~08 | 可用（The Record / Packet Storm 走此路径） |

铁律：S1.5/S2/S3 的结果必须标注渠道；S1 未恢复前，禁止声称读过 Folo/Reddit 订阅。
资源雷达是**聚合器不是新社区**：其上游渠道写入 `entries.origin_source`，sources 表只保留 1 个 kind=aggregator 的渠道行，
禁止把 `tg-cn-deals`、`rss-ithome` 等上游 ID 误注册成独立来源。

### 2.0 安全 / 黑客技术情报源（2026-11-19 新增，全部零凭证实采验证）

| source_id | 站点 | 定位 | 采集入口 | 实测 |
|---|---|---|---|---|
| `thehackernews` | The Hacker News | 全球访问量最大的黑客/安全新闻站，漏洞与在野攻击首发多出于此 | RSS（`thehackernews.com/feeds/posts/default?alt=rss`） | PASS |
| `krebs` | Krebs on Security | Brian Krebs，深度网络犯罪调查，金融/黑产链条一手报道 | RSS | PASS |
| `darkreading` | Dark Reading | 企业安全媒体，CISO 视角的威胁面与治理情报 | RSS | PASS |
| `hackread` | HackRead | 黑客事件/数据泄露快讯，覆盖勒索与暗网 | RSS | PASS |
| `cyberscoop` | CyberScoop | 美国网络安全政策、CISA/国会动态 | RSS | PASS |
| `cybersecuritydive` | Cybersecurity Dive | 行业侧安全事件与厂商动向，适合做趋势背景 | RSS | PASS |
| `securelist` | Securelist（Kaspersky） | APT 组织与恶意软件家族研究，含样本技术细节 | RSS | PASS |
| `portswigger_research` | PortSwigger Research | Web 安全顶流研究（Burp 团队），XSS/请求走私等 PoC 与手法 | RSS | PASS |
| `seclists_fd` | Seclists Full Disclosure | 漏洞公开披露邮件列表，PoC 与 0day 讨论原产地 | RSS | PASS |
| `seebug_paper` | 先知社区 paper.seebug.org | 中文漏洞研究质量最高的一档，含代码审计与利用分析 | RSS | PASS |
| `infosecurity_mag` | Infosecurity Magazine | 英国老牌安全 industry 媒体，合规/治理/行业动向 | RSS | PASS |
| `securityaffairs` | Security Affairs | Pierluigi Paganini，APT 与网络犯罪事件追踪，出稿快 | RSS | PASS |
| `github_advisories` | GitHub Security Advisories | GHSA + CVE + CVSS + 受影响包与修复版本，可直接落依赖升级动作 | 公开 JSON API | PASS |
| `cisa_kev` | CISA KEV | 官方「已确认在野利用」清单，含处置截止日，判断优先级的最硬证据 | 公开 JSON | PASS |

### 2.0.1 受限安全源（`sec_restricted`，三级回退，2026-11-19 实测）

这五站对 `requests` 默认 TLS 指纹返回 403 / 挑战页，因此单独成组，**逐站**按顺序试：

```
curl_cffi（impersonate=chrome）→ 本地代理（SKILLKIT_PROXY）→ 无头浏览器（Playwright + 内置 chromium）→ 跳过
```

浏览器只在轻量通道全败时才启动，整组共用一次会话；全败的站跳过，不伪造条目、不影响同组其它站。

| 站点 | 拦法 | 实测解法 | 状态 |
|---|---|---|---|
| Exploit-DB | TLS 指纹拦截（curl 通、requests 不通） | `curl_cffi impersonate=chrome` 直连 200 | **已解决**（需 `pip install curl_cffi`） |
| SecurityWeek | 直连 403 | 经 `SKILLKIT_PROXY` 代理 200 | **已解决（需代理）** |
| BleepingComputer | Cloudflare 托管挑战 | 前两级 403，**无头浏览器 200，RSS 15 条可解析** | **已解决**（`via=browser`） |
| The Record | Cloudflare「Just a moment」托管挑战 | 前两级 403；无头浏览器同样 403 且挑战不自过 | **未解决**：需真实浏览器指纹（`headless=False` 或 Camoufox） |
| Packet Storm | feed 全部重定向到 `packetstorm.news` 的 TOS 同意页（接口内 base64 回跳） | 首页确在，但按钮被 CSS 隐藏，无头下点不到 | **未解决**：需人工过一次 TOS 或带 cookie 复用 |

后两站在 `RESTRICTED_FEEDS` 里标 `browser_ok=False`，不再尝试浏览器——否则每次采集白等 20 秒（实测 50s → 10.6s）。

配置（均可选）：

```powershell
# .env：代理，只影响 SecurityWeek 这类「直连被拒但无 JS 挑战」的站
SKILLKIT_PROXY=http://127.0.0.1:3067
# .env：覆盖浏览器内核路径（默认用 D:\00_skiill_ku\01_crawler\runtime 里的 chromium-1243）
SKILLKIT_BROWSER_EXE=D:\00_skiill_ku\01_crawler\runtime\Playwright\chromium-1243\chrome-win64\chrome.exe
```

**铁律**：`sec_restricted` 的每条记录带 `extra.via`（`impersonate` / `proxy` / `browser`），报告里引用时必须标注实际通道；
被跳过的两站不得写成「已读」，也不得用记忆补内容。

**用法要点**：
- 安全情报必须区分三种证据强度：`CISA KEV / GitHub Advisory`（有编号有修复）> `厂商研究博客`（有技术细节、无编号）> `媒体快讯`（有事件、无细节）。
- 回答「某个漏洞/攻击是否严重」时，优先查 `cisa_kev` 是否收录 + `github_advisories` 的 CVSS，再补媒体解读，禁止只引媒体标题。
- 中文源（先知）与英文源（THN/Krebs）同时命中 = 跨源复现，权重最高。
资源雷达是**聚合器不是新社区**：其上游渠道写入 `entries.origin_source`，sources 表只保留 1 个 kind=aggregator 的渠道行，
禁止把 `tg-cn-deals`、`rss-ithome` 等上游 ID 误注册成独立来源。

### 2.0.2 正文层：RSS 是目录，不是内容（`fetch_bodies.py`，2026-11-19 新增）

**这是本 Skill 之前最大的一个坑**：所有 RSS / API 采集只给出标题 + 一两句摘要，实测库里
security 分类平均摘要 **254 字符**、65 条里仅 9 条超过 400 字符。只存摘要等于存了个书签——
FTS 能命中，但要拿到"影响哪些版本、怎么利用、有没有 PoC"仍然得点链接。

规矩：

1. **采集（discovery）与抓正文（content）是两道工序，不许当成一道。** 采集只负责"知道有什么新的"，
   正文必须由 `fetch_bodies.py` 回源，落 `article_bodies` 表。
2. **引用正文前必须确认 `article_bodies.status='ok'`。** 只有摘要时，只能说"据标题/摘要"，
   不许展开成技术细节——那是编的。
3. **正文通道同样三级回退**：`HttpClient` → `curl_cffi` → 无头浏览器，记录 `via`。
   实测 BleepingComputer 的文章页对纯 HTTP 返回 403、要浏览器才拿到正文。

```powershell
# 抓最近 30 条安全类条目正文
python 06_techradar/scripts/fetch_bodies.py --db 06_techradar/data/techradar.db --category security --limit 30
# 全部分类（PowerShell 会吞掉空串，务必用 --all）
python 06_techradar/scripts/fetch_bodies.py --db 06_techradar/data/techradar.db --all --limit 15
# 纯 HTTP 环境：禁用无头浏览器第三级
python 06_techradar/scripts/fetch_bodies.py --db 06_techradar/data/techradar.db --limit 10 --no-browser
# 只看进度与成功率（不抓）
python 06_techradar/scripts/fetch_bodies.py --db ... --stats
# 重试上次失败的（付费墙/临时 5xx 等）
python 06_techradar/scripts/fetch_bodies.py --db ... --retry-failed --limit 20
```

正文抽取引擎优先级：`trafilatura`（已装，首选）→ `readability-lxml` → 内置正则兜底。
`status` 取值：`ok` / `http_error` / `blocked` / `too_short`（<200 字符，多为付费墙或反爬占位）/ `not_html` / `error`。
**`too_short` 不是失败到可以忽略，它意味着这篇文章我们没有内容，回答时必须降级表述。**

`daily` 任务已内置一轮 30 条补抓（`lifecycle_run.py` 的 `run_collectors`），长尾由后续轮次自然补齐。

### 2.0.3 排障型情报源（radar v2，2026-11-24 新增）

> 目标：让雷达从“新闻公告板”变成“排障外置大脑”。采集源从“新闻”扩展到“可执行的技术答案”，
> 检索时技术意图优先返回知识库 / Issues / Stack Overflow，而不是安全新闻。

| source_id | 来源 | 采集入口 | 关键参数 | 实测 |
|---|---|---|---|---|
| `knowledge_base` | 实战复盘知识（headless/offscreen、curl_cffi、Reddit DOM、schtasks S4U） | `import_knowledge.py` | `--db`、`--dry-run` | 4 条已入库，幂等 |
| `stackoverflow` | Stack Overflow 指定 Tag 问答 | `collect_stackoverflow.py` | `--tags`（默认 `playwright,python-requests`）、`--limit` | fetched=6 inserted=6 |
| `github_issues` | GitHub Issues 排障搜索 | `collect_github_issues.py` | `--queries`（默认 4 条反爬/权限查询）、`--limit` | fetched=4 inserted=4 |
| `reddit_tech` | Reddit 技术板块 r/webscraping、r/Python | `collect_reddit_topics.py` | `--subreddits`（默认 `webscraping,Python`）、`--limit` | fetched=6 inserted=6；浏览器登录态 + DOM，8–15s 间隔 |

- 三个新采集器均走统一管线（`run_source` → 去重 → FTS5 → `source_registry`），单源失败只降级该源。
- `lifecycle_run.py` 的 daily 已接入三条新源（各 6–10 条/轮）+ `tagging.py --hours 3`。
- 配额：StackExchange 300/天；GitHub 未认证 10 次/分钟（可配 `GITHUB_TOKEN`）；Reddit 技术板块单轮 8–15 秒/板块。

### 2.1 资源雷达接入事实（实测，勿臆造）

- 公开只读接口：`GET /health`、`GET /api/items`（支持 `kind/category/limit/offset`；`q/source_id` 服务端不过滤，需客户端筛）、
  `GET /api/items/{id}`（详情含 `content` 正文，部分条目为 null）、`GET /api/sources`、`/api/stats`、`/api/rss`。
- 管理接口返回 401「需要管理密码」，不触碰、不尝试绕过。
- 条目自带：原始链接 `url`、规范化 `url_key`、`kind`（freebie/deal/opensource/news/info/noise）、
  27 类 `category`、AI 定级 `ai.keep/quality/reason`、`score`、`first_seen_at/last_seen_at`、`status(active/expired)`、`dupCount`。
- 已知限制：演示站 4 个 github-readme 采集器当前 **enabled=false**（最近运行 2026-11-13/14），GitHub 类仅余历史库存；
  正文覆盖率低（实测 8 条详情仅 2 条有 content），线索价值大于全文价值；站点偶发读超时，采集器内置退避重试。

### 2.2 双通道采集体系（通道 A / 通道 B，统一入库）

两个通道相互独立、互不阻塞，共用同一套管线：发现 → 采集 → 解析 → 标准化 → 去重 → 质量校验 → SQLite 入库 → FTS5 索引 → `radar_query.py` 检索。

| 通道 | 采集对象 | 凭据 | 执行入口 | 无凭据时的行为 |
|---|---|---|---|---|
| **A 公开** | Hacker News、GitHub 公开搜索/Release Atom、Hugging Face 模型与数据集/Daily Papers、arXiv、官方技术博客 RSS/Atom、资源雷达公开只读 API | **零** | `python 06_techradar/scripts/collect_public_suite.py` | 照常运行 |
| **B 认证** | Folo 用户订阅与正文 | Folo 会话 Cookie | `python 06_techradar/scripts/collect_folo.py` | `AUTH_REQUIRED`，输出配置指引，不影响通道 A |
| **B 认证** | Reddit 官方 Data API 帖子 | OAuth client_credentials | `python 06_techradar/scripts/collect_reddit.py` | `APPROVAL_REQUIRED`，输出审批指引，不影响通道 A |

- 认证方式（已实现，非占位）：
  - Folo：Base `https://api.follow.is`，Cookie `__Secure-better-auth.session_token=<FOLO_SESSION_TOKEN>;`，
    接口 `GET /subscriptions`、`POST /entries`（支持 `publishedAfter` 增量 + `withContent`）。
    **接口依据为第三方开源实现 `folo-mcp`（hyoban，v1.0.0，MIT），不是 Folo 官方 MCP 或官方文档化 API**；
    该实现通过浏览器会话 Cookie 访问内部接口，属第三方接口观察，**存在随 Folo 前端升级而失效的兼容风险**。
    Folo Cookie 是敏感会话凭据：只允许用户在本地 `.env` 填写，**不得发送给任何 AI 助手**，不得写入日志/报告/数据库。
  - Reddit：`POST https://www.reddit.com/api/v1/access_token`（client_credentials）→ Bearer，
    接口 `https://oauth.reddit.com/r/<sub>/new`，`after` 游标分页；严格使用真实 User-Agent，不使用未授权接口或 RSS 镜像。
- 增量与断点：Folo 按 feed 记录 `publishedAfter` 水位（`data/folo_checkpoint.json`），Reddit 按 sub 记录最新时间
  （`data/reddit_checkpoint.json`）；失败不前移水位，可重跑。
- 凭据安全：只从环境变量或 `.env` 读取（模板见仓库根 `.env.example`），`.env` 已被 `.gitignore` 排除；
  日志经 `loggingx.mask` 脱敏；代码与报告中不出现任何 Token/Cookie/Secret。
- 故障隔离：来源之间、博客之间、subreddit 之间、feed 之间逐级隔离；单个来源失败只把该来源标为 `DEGRADED`，
  调度器不会因此退出。每日任务的采集器退出码 `3` 表示"认证源被阻塞"，不算采集失败。
- 测试/CI：`TECH_RADAR_DISABLE_BROWSER=1` 可禁用浏览器回退，认证源按 `BLOCKED/AUTH_REQUIRED` 处理，不启动 Chrome。

### 2.3 统一 Source Registry

表 `source_registry` 记录：`source_id / source_name / source_type / channel / auth_required /
implementation_status / configuration_status / authorization_status / credential_status /
connectivity_status / collection_status / status / enabled / last_attempt_at / last_success_at /
last_checked_at / last_error / items_fetched / items_inserted / items_deduped / notes`。

**六态分离，互不替代**（单一 `status` 只是派生摘要，不得用它推断"在线"或"最近成功"）：

| 字段 | 取值 | 含义 |
|---|---|---|
| implementation_status | IMPLEMENTED / NOT_IMPLEMENTED | 适配器代码是否已实现 |
| configuration_status | CONFIGURED / UNCONFIGURED / PARTIAL / UNKNOWN | 凭据与参数是否配好 |
| authorization_status | not_required / pending / approved / rejected / unknown | 官方授权/审批状态 |
| credential_status | not_required / missing / invalid / valid | 凭据本身是否有效 |
| connectivity_status | unknown / online / offline / blocked | 最近一次探测的连通性 |
| collection_status | NEVER_RUN / SUCCESS / PARTIAL / FAILED / BLOCKED | 最近一次采集结果 |
| status（派生） | READY / AUTH_REQUIRED / APPROVAL_REQUIRED / DEGRADED / DISABLED / BLOCKED | 综合可用性摘要 |

**语义纪律**：
- `READY` 只表示"实现完成且具备运行条件"，**不等于在线、也不等于最近一次采集成功**；
  判断可用性必须同时看 `connectivity_status` 与 `collection_status`。
- 尚未探测过的来源，`connectivity_status` 必须是 `unknown`，不能默认写成 online。
- 成功采集后写 `last_success_at` 与 `collection_status=SUCCESS`；失败写 `last_error` 并降级。
- 认证源未获授权（AUTH_REQUIRED / APPROVAL_REQUIRED）**不影响公开源的整体状态**，故障隔离保持不变。

巡检命令：`python 06_techradar/scripts/source_status.py`

## 3. 本地情报库（Schema v3，2026-11-17 增量迁移）

- 位置：默认 `D:\\00_skiill_ku\\06_techradar\\data\\techradar.db`（SQLite，单文件，易备份）。
- 表：`sources / entries / projects / tags / insights / relations / snapshots / analysis_runs / schema_meta`。
- 去重两层：
  - 直采：`entries.content_hash` 唯一索引（小写 URL + 标题哈希），重复返回 `duplicate`。
  - 聚合源：`entries.external_key` 唯一索引（如 `zcl:41238`），重复采集只更新观测字段（`updated`），不新增行。
- 跨源关联：`entries.canonical_key`（见 `skillkit/canonical.py`），GitHub 仓库收敛到 `owner/repo`、剥离跟踪参数；
  `IntelDB.find_canonical_group(url)` 查同主题跨渠道条目，`canonical_groups()` 列多源复现主题。
- 溯源字段：`aggregator`（聚合渠道）+ `origin_source`（上游源 ID）+ 原始 `url`；上游源不另立 sources 行。
- 时间与失效：`first_seen_at / last_seen_at` 分别记录首末见；`link_status` 标 active/expired/unknown；
  AI 分类存 `ai_category`，纠错写 `corrected_category`（`correct_category()`，不覆盖原值，可审计）。
- 迁移保证：v1→v2 全部 ADD COLUMN + 回填，旧数据零破坏；迁移前备份在 `_backup/<ts>/`。
- 读取状态机：`title_scanned → content_fetched → content_read → analyzed → archived`，只允许前进。
  - `title_scanned`：仅标题可见；`content_fetched`：正文已拉取；`content_read`：正文已阅读；
    `analyzed`：已产出分析结论；`archived`：已归档但保留可查。
  - 升级必须走 `IntelDB.mark_read_state(url, state)` 或 `radar_query.py --mark-fetched`，禁止批量伪造。
- 向量库暂不引入：先保证采集与去重可靠；出现语义检索刚需再评估。

## 4. 采集命令

```powershell
# 资源雷达（S1.5 二级聚合，公开只读 API）
python 06_techradar/scripts/collect_zcl.py --db 06_techradar/data/techradar.db `
  --max-items 60 --detail-limit 10 --report _reports/zcl_collect_<ts>.json
# 幂等验证：立即再跑一次，预期 inserted=0 updated=N 且总行数不变

# 公开源直采（S2）
python 06_techradar/scripts/collect_public.py --db 06_techradar/data/techradar.db --source both --limit 10

# 安全 / 黑客技术情报（S2，2026-11-19 新增；12 站 RSS + GitHub Advisory + CISA KEV）
python 06_techradar/scripts/collect_public_suite.py --db 06_techradar/data/techradar.db `
  --only sec_rss,github_advisories,cisa_kev --limit 10 --report _reports/security_collect.json
# 全部通道 A 源（含安全源）
python 06_techradar/scripts/collect_public_suite.py --db 06_techradar/data/techradar.db --limit 20

# 场景检索（本地库，无外部请求；支持 FTS5 全文 + 时间/标签/来源/关联过滤）
python 06_techradar/scripts/radar_query.py --db 06_techradar/data/techradar.db `
  --scenario ai-robot --since 2026-11-01 --out _reports/q_robot.json
# 可选 scenario：ai-robot | small-model | douyin-growth | ai-agent | custom --keywords a,b,c
# 可选参数：--text "自由文本" --until 2026-11-30 --tag 标签 --source 来源 --related <entry_id>
#          --engine auto|fts5|like --init-fts --mark-fetched
```

Folo/Reddit 恢复后的适配要求：直采走 `add_entry`；聚合类采集走 `upsert_aggregated_entry`，
评论精读后 `mark_read(url, "comments_read")`；新采集器放 `scripts/` 并登记本文件。

### 4.0.1 排障型采集与知识入库（radar v2）

```powershell
# Stack Overflow（默认 tags: playwright,python-requests）
python 06_techradar/scripts/collect_stackoverflow.py --db 06_techradar/data/techradar.db `
  --tags playwright,python-requests --limit 8

# GitHub Issues（默认 4 条反爬/权限查询；可用 GITHUB_TOKEN 提高配额）
python 06_techradar/scripts/collect_github_issues.py --db 06_techradar/data/techradar.db `
  --queries "playwright 403 bypass,schtasks 0x80070005" --limit 6

# Reddit 技术板块（浏览器登录态 + DOM，8–15s 间隔）
python 06_techradar/scripts/collect_reddit_topics.py --db 06_techradar/data/techradar.db `
  --subreddits webscraping,Python --limit 10

# 实战知识入库（幂等；先 --dry-run 预览）
python 06_techradar/scripts/import_knowledge.py --db 06_techradar/data/techradar.db --dry-run
python 06_techradar/scripts/import_knowledge.py --db 06_techradar/data/techradar.db
python 06_techradar/scripts/ingest_case_notes.py --db 06_techradar/data/techradar.db

# 标签补标（daily 已自动跑 --hours 3）
python 06_techradar/scripts/tagging.py --db 06_techradar/data/techradar.db --hours 6
python 06_techradar/scripts/tagging.py --db 06_techradar/data/techradar.db --all --batch 3000

# 技术意图检索：优先知识库 / Issues / SO，过滤安全新闻
python 06_techradar/scripts/radar_query.py --db 06_techradar/data/techradar.db `
  --text "windows 计划任务 SYSTEM 权限" --intent tech --limit 5
python 06_techradar/scripts/radar_query.py --db 06_techradar/data/techradar.db `
  --tag windows-permission --limit 5
python 06_techradar/scripts/radar_query.py --db 06_techradar/data/techradar.db `
  --text "playwright 403" --order cross_source_desc --limit 5
```

### 4.0.2 主题补采与案例笔记

```powershell
# 本地库缺某领域内容时，按主题从 HN / GitHub 补采
python 06_techradar/scripts/collect_topic.py --db 06_techradar/data/techradar.db `
  --topic "web scraping" --source hn --limit 10

# 把实战案例写成 knowledge_base 条目（按 URL+标题去重，可重复执行）
python 06_techradar/scripts/ingest_case_notes.py --db 06_techradar/data/techradar.db
```

## 4.1 场景研判 Playbook（回答具体项目需求时必须执行）

1. 先 `radar_query.py --scenario <预设>` 取证据候选，零命中必须显式声明，禁止用记忆补。
2. 每条候选核验五要素：原始链接可打开、发布时间、上游来源、热度指标（score/star/评论）、`link_status`。
3. 跨源复现（`cross_source_count>1`）权重最高；单次曝光不判趋势，需 `last_seen_at` 多日复现。
4. 按场景扩展关键词面，不局限字面：
   - **AI Robot**：VLA、具身/世界模型、sim2real、端侧推理（TensorRT/ONNX/量化）、数据采集与合成、多 Agent 协作、低成本传感。
   - **小模型训练**：LoRA/QLoRA/DPO、蒸馏、数据合成、GGUF/AWQ/GPTQ、llama.cpp/MLX、评测 benchmark、开源数据集、低成本训练部署。
   - **抖音增长**：ffmpeg/Remotion 自动化、TTS/字幕、素材发现与授权、热门内容结构分析、合规数据分析；刷量类只解读风险不给执行方案。
5. 输出「技术组合」而非帖子清单：每项给组件职责、数据流、最小验证动作、成熟度、风险、证据链接。
6. 关键词召回天然有噪音（如音乐播放器误命中 agent 词），分析层必须二次筛选并说明淘汰理由。

## 4.2 三级执行模式（按任务规模选择，不可一律走深度）

| 模式 | 适用 | 必做动作 | 输出 |
|---|---|---|---|
| 轻量情报模式 | 单个模型/工具/项目查询、单个仓库评估、轻量比较、一次性动态查询 | 定向查询；必要时查本地库；必要时补公开源 | 关键证据 + 判断 |
| 深度研究模式 | 跨领域研究、路线比较、可行性研究、创新探索、开源生态评估、趋势分析 | 查本地情报 → 多可信源检索 → 项目/论文/文档/版本取证 → 重要事实交叉核验 → 方案/依赖/风险/可行性分析 | 有来源的综合判断 + 技术组合 |
| 持续维护模式 | 定期采集、持续跟踪、知识库维护、定时任务接管、备份归档清理 | 检查 DB/采集脚本/调度任务 → 幂等安装或更新任务 → 运行维护脚本 | 执行日志 + job_runs 记录 |

判据：只要用户问的是"最近/最新/有哪些值得"，就必须先查本地库再补公开源；
只问"某个具体项目怎么用"且不涉及趋势与选型时，可走轻量模式。

## 4.3 按需深度阅读（read_state 四级，禁止伪造）

标题扫描 ≠ 读完情报。状态机只允许前进，且每一级必须对应真实动作：

```
title_scanned → content_fetched → content_read → analyzed → archived
```

| 状态 | 何时可以推进 | 记录 |
|---|---|---|
| title_scanned | 采集入库时（轻量流程） | 默认值 |
| content_fetched | 真的抓取到正文并写入 `extra_json.content`（≥200 字符、内容类型合法） | `read_log` 一行 fetch/SUCCESS |
| content_read | 模型/人真的读过正文（按需） | `read_log` 一行 read/SUCCESS |
| analyzed | 已形成有证据的结论（必须给 `--claim`，写入 insights） | `read_log` 一行 analyze/SUCCESS |
| archived | 归档（保留可查） | 人工/策略 |

执行入口：`python 06_techradar/scripts/radar_read.py`

```powershell
# 1) 先用 FTS/标签筛选候选（不抓正文）
python 06_techradar/scripts/radar_read.py --db 06_techradar\data\techradar.db `
  --query "vision language action" --limit 8
# 2) 对候选按需抓正文并推进到 content_fetched（robots 不允许则跳过）
python 06_techradar/scripts/radar_read.py --db ... --entry-id 123 --fetch
# 3) 真正阅读后推进 content_read
python 06_techradar/scripts/radar_read.py --db ... --entry-id 123 --mark-read
# 4) 形成有证据结论后推进 analyzed（写 insights）
python 06_techradar/scripts/radar_read.py --db ... --entry-id 123 --mark-analyzed --claim "结论..."
```

硬约束：
- 抓取失败不推进状态、不移动增量水位；失败写入 `read_log` 并保留错误。
- 尊重 robots.txt（Disallow 命中即跳过）、访问频率与站点条款；只访问公开 URL。
- 不批量伪造阅读状态；`title_scanned` 占比高是正常的（说明只做了标题级采集）。
- 复用 `skillkit.http` 与 `IntelDB`，不另建爬虫实现。

## 4.4 关联能力边界（不是知识图谱）

当前可用的关联方式只有五类，查询与报告中必须**明确说明用的是哪一种**：

| 类型 | 依据 | 可靠性 |
|---|---|---|
| 关键词关联 | 标题/摘要/正文的词面命中（FTS5 / LIKE） | 弱：同词不同义会误召 |
| 标签关联 | `tags` / `entry_tags`（采集器写入，人工可修正） | 中：依赖标注质量 |
| 同项目跨来源关联 | `canonical_key` 相同（同一 URL/仓库收敛） | 强：可验证的同一对象 |
| 显式关系 | `relations` 表（人工或规则确认后写入） | 强：必须写 note 说明依据 |
| 来源共现 | 同一 `origin_source` / `aggregator` 下同时出现 | 弱：仅表示同渠道 |

纪律：
- **不得**把"关键词共同出现"宣传成知识图谱或因果关系；
- `relations=0` 是允许且诚实的初始状态，禁止为凑数生成虚假关联；
- 只有存在可核验证据（同一项目、明确依赖、官方说明、人工确认）时才调用 `link_relation()` 写入。

### 4.5 脚本清单（2026-11-24 核对，实际 23 个 .py）

> 旧版本文写“14 个脚本”，与目录实际不符；以本节与 [CLI_REFERENCE.md](./CLI_REFERENCE.md) 为准。
> 下表“关键参数”只列高频项，完整参数见自动生成的 CLI_REFERENCE。

| 脚本 | 职责 | 关键参数 |
|---|---|---|
| `collect_public_suite.py` | 通道 A 编排：HN/GitHub/HF/arXiv/RSS/安全源/资源雷达 | `--only`、`--limit`、`--report` |
| `collect_public.py` | HN / GitHub 公开源直采 | `--source`、`--limit`、`--query` |
| `collect_zcl.py` | 资源雷达（112 源聚合，公开只读 API） | `--max-items`、`--detail-limit`、`--page-size`、`--kinds`、`--categories` |
| `collect_folo.py` | Folo：令牌优先，缺令牌走浏览器登录态 | `--limit`、`--max-feeds`、`--report` |
| `collect_reddit.py` | Reddit：OAuth2 优先，缺凭据走浏览器登录态 | `--subreddits`、`--limit`、`--report` |
| `collect_reddit_topics.py` | Reddit 技术板块（排障型） | `--subreddits`、`--limit` |
| `collect_github_issues.py` | GitHub Issues 排障搜索 | `--queries`、`--limit` |
| `collect_stackoverflow.py` | Stack Overflow 指定 Tag | `--tags`、`--limit` |
| `collect_topic.py` | 主题驱动的 HN/GitHub 补采 | `--topic`、`--source`、`--limit` |
| `fetch_bodies.py` | 正文回源（HTTP → curl_cffi → 浏览器三级） | `--category`、`--all`、`--since`、`--limit`、`--retry-failed`、`--stats`、`--sync-read-state`、`--no-browser` |
| `import_knowledge.py` | 实战知识写入 knowledge_base（4 条，幂等） | `--db`、`--dry-run` |
| `ingest_case_notes.py` | 实战案例笔记入库（knowledge_base） | `--db` |
| `tagging.py` | 特征标签自动打标 / 全量补标 | `--hours`、`--all`、`--batch` |
| `radar_query.py` | 本地检索：FTS5 / LIKE / 时间 / 标签 / 来源 / 关联 / 意图 | `--scenario`、`--text`、`--keywords`、`--since`、`--until`、`--tag`、`--source`、`--related`、`--engine`、`--intent`、`--order`、`--init-fts`、`--mark-fetched`、`--limit`、`--out` |
| `radar_read.py` | 按需深度阅读状态机（只前进） | `--query`、`--entry-id`、`--fetch`、`--mark-read`、`--mark-analyzed`、`--claim`、`--dry-run` |
| `lifecycle_run.py` | daily/weekly/monthly/quarterly 生命周期 | `--job`、`--apply`、`--config`、`--no-collect`、`--report-dir` |
| `scheduler.py` | 计划任务检查/安装/触发测试 | `--action status\|install\|trigger-test\|remove` |
| `healthcheck.py` | 数据源健康检查 | `--out`、`--mcp-folo`、`--mcp-reddit`、`--mcp-config` |
| `source_status.py` | `source_registry` 巡检 | `--json` |
| `websession.py` | 浏览器会话：拉起/复用/残留清理（库模块） | 无 CLI，供采集器 import |
| `proxy_env.py` | 本机代理探测（3067 等，库模块） | 无 CLI，供 HttpClient/Chrome 使用 |
| `public_sources.py` | 安全/黑客源适配器（库模块） | 无 CLI，供 `collect_public_suite` 调用 |
| `snippets.py` | `<pre><code>` / 围栏代码块抽取（库模块） | 无 CLI，供采集器与正文回源调用 |

### 4.6 标签体系（radar v2）

`tagging.py` 按标题/摘要/正文规则打标，`radar_query.py --tag` 直接消费：

| 标签 | 触发特征 | 当前规模（2026-11-24） |
|---|---|---:|
| `troubleshooting` | error/exception/timeout/failed/0x…/报错/失败/排查 | 192 |
| `anti-bot` | 403/401/429/cloudflare/captcha/headless/反爬/风控 | 57 |
| `code-snippet` | 含 `<pre><code>` 或 ``` 围栏代码 | 44 |
| `windows-permission` | schtasks/SYSTEM/S4U/Access is denied/权限/提权 | 4 |
| `playwright` / `curl-cffi` / `reddit` | 技术栈关键词 | 按命中 |

- 新采集自动打标：daily 内置 `tagging.py --hours 3`；历史数据用 `--all` 幂等补标。
- 标签只做“检索入口”，不等于因果结论；回答时仍需回到原始链接与正文。

### 4.7 知识库（knowledge_base）

- `import_knowledge.py`：4 条已验证实战知识（headless/offscreen、curl_cffi 边界、Reddit DOM、schtasks S4U），
  正文含可执行代码，`content` 写入 `extra_json` 并自动进 FTS5。
- `ingest_case_notes.py`：把新的实战案例按标准管道写入 `knowledge_base`，按 `URL + 标题` 去重，可重复执行。
- 检索优先级：`knowledge_base` 在 `TECH_SOURCE_PRIORITY` 首位；`--intent tech` 时先查知识库，
  再查 GitHub Issues / Stack Overflow / Reddit 技术板块。
- 纪律：知识库条目必须带“结论 + 可执行代码 + 适用边界 + 验证方法”，不得把未验证的猜测写成知识。

### 4.8 代码片段抽取与检索权重

- `snippets.py` 支持两类输入：HTML 的 `<pre><code>`、Markdown 的 ``` 围栏。
- Stack Overflow / GitHub Issues 采集时把代码块写入 `extra_json.code_snippets`；
  `fetch_bodies.py` 在正文末尾追加 `【代码片段】` 区块，使代码进入 `article_bodies.body` 与 FTS5。
- 检索建议：排障问题优先用 `--intent tech` 或 `--tag code-snippet`，命中后再回源确认版本与适用性。

## 5. 技术评估维度（热度与价值分开）

新颖性、热度变化、实用性、成熟度、可实现性、组合价值、成本、许可证、安全风险。
Star/Upvote 只作热度输入；跨源复现 + 评论区实证 + 可运行件 + 与现有栈的连接点，权重高于单源爆款。

## 6. 情报持续采集与数据库生命周期管理（**强制能力**）

> 这不是可选脚本，而是 Skill 的一部分：Agent 必须保证这套机制存在、可运行、可审计、可迁移。
> 规则写在本文件里，脚本只是执行器；Skill 升级后 Agent 应按本文件同步任务配置。

### 6.1 四类周期任务（缺一不可）

| 任务 | 唯一 ID | 周期 | 执行器 | 职责 |
|---|---|---|---|---|
| 每日 | `TechRadar_Daily` | 每天 07:30 | `lifecycle_run.py --job daily` | 采集 Folo/Reddit/GitHub/资源雷达已启用源 → 去重/分类/入库 → 更新失效状态 → 重算价值分 → 记录热度快照 |
| 每周 | `TechRadar_Weekly` | 每周日 08:00 | `--job weekly` | 来源健康、失效链接、重复内容、低价值清理计划（默认只出计划） |
| 每月 | `TechRadar_Monthly` | 每月 1 日 09:00 | `--job monthly` | 完整备份、`integrity_check`、价值重评、快照降采样、归档、清理（默认 dry-run） |
| 每季度 | `TechRadar_Quarterly` | 1/4/7/10 月 1 日 10:00 | `--job quarterly` | 信息源审计、长期档案与库结构审计、采集策略建议，只出报告不删数据 |

调度优先级：Windows 任务计划程序（`schtasks`）> cron > 手动。任务**必须独立于 AI 对话**运行，
不依赖 Trae/任何客户端常驻；客户端关闭不影响任务执行。

### 6.2 保留策略（写死在本 Skill，脚本从配置读取）

| 数据类别 | 默认保留 | 动作 |
|---|---|---|
| 普通帖子正文 | 180 天 | 过期清理 |
| Reddit 条目/评论 | 90 天 | 过期清理 |
| GitHub 项目资料 | 长期（3650 天）并定期更新 | 保留 |
| 技术洞察 / 创新方案 / 高价值项目 / 人工收藏 | 永久 | 永不自动删除 |
| 热度快照 | 90 天原始；90–400 天按天降采样；更早按周 | 降采样归档 |
| 无价值推广（goods/trade/invite/carpool） | 7 天 | 清理 |
| 其它低值（other/noise/pan 等） | 14–30 天 | 清理 |
| 失效链接 | 先进入 14 天观察期 | 观察期后再按类别处理 |

配置入口：`06_techradar/data/lifecycle_config.json`（`retention_days` / `low_value_categories` / `observation_days`）。
策略同时写入 `retention_policy` 表，供审计与跨客户端读取。

### 6.3 情报价值动态评分（可解释，0–100）

| 维度 | 权重 | 说明 |
|---|---|---|
| 新颖性 | 30 | 按发布时间指数衰减（120 天半衰），旧内容自然降权 |
| 实际价值 | 20 | 上游 AI 质量星级优先，其次按形态（opensource/info > deal/freebie > noise） |
| 社区讨论 | 15 | points/stars/评论数对数饱和 |
| 维护状态 | 10 | 最近仍被观测到；GitHub 类额外加分 |
| 跨源复现 | 10 | 同一 canonical_key 被多个渠道覆盖 |
| 项目相关性 | 15 | 命中用户项目画像（ai-robot / small-model / douyin-growth / ai-agent） |

分档：`P0 永久`（收藏/洞察/质量 5 星/千级热度/高分）、`P1 长期`（GitHub、强信号、65+）、
`P2 标准`（180 天）、`P3 低值`（30 天）。
**硬规则：不因「暂时不热门」降档**——GitHub 项目、质量 4–5 星、千级社区热度的历史条目一律 P0/P1。

### 6.4 删除安全（四道闸，任何一道不满足都不许删）

1. **备份**：真实删除前用 SQLite 在线备份 API 写 `_backup/lifecycle/<ts>_<job>/`，并记录 SHA256。
2. **dry-run**：默认 `--apply` 缺省即 dry-run；即使传 `--apply`，配置 `apply_purge=false` 仍强制 dry-run。
3. **删除日志**：先写 `purge_log`（整行 JSON + 原因 + 分值 + 字节数），再 `DELETE`。
4. **恢复**：`restore_purges()` 可从 `purge_log` 回插整行；`restored_at` 留痕，已存在则跳过。

永久保护集合：`is_pinned=1`、`insights` 证据引用、`read_state=deep_read`、`value_tier=P0`。
这些条目**任何策略、任何参数都不会入选清理计划**。

### 6.5 执行记录（每次运行必写 `job_runs`）

字段：`job_name / mode(dry-run|apply) / started_at / finished_at / collected / inserted /
deduped / failed / purged / bytes_freed / status(PASS|PARTIAL|FAIL) / detail_json`。
中断回收：超过 30 分钟仍为 `running` 的记录由 `reap_stale_runs()` 标为 FAIL，不留假状态。

### 6.6 调度器与任务注册表（机器可读，跨客户端）

```powershell
python 06_techradar/scripts/scheduler.py --action status        # 检查任务与最近运行
python 06_techradar/scripts/scheduler.py --action install       # 幂等安装/同步（已存在→EXISTS_OK）
python 06_techradar/scripts/scheduler.py --action trigger-test  # 首次触发并回查 job_runs
python 06_techradar/scripts/scheduler.py --action remove        # 卸载（需人工确认）
```

- 注册表：`06_techradar/data/TASK_REGISTRY.json` + SQLite `task_registry` 表，记录
  任务名、唯一 ID、周期、脚本路径、参数、Skill 版本、最后运行时间、最后状态、配置哈希。
- Windows 用 `.cmd` 包装脚本（`06_techradar/scripts/tasks/*.cmd`）调用 Python，固定工作目录并重定向日志到
  `_logs/scheduler/`；**不要**把 `python.exe` 直接作为任务目标（控制台会以 0xC000013A 终止）。
- 幂等：按 `config_hash`（脚本+参数+周期+Skill 版本）比对，一致则不动，不一致才 `/Change`。

### 6.7 跨客户端接管流程

新客户端/新 Agent 接入时：读本 Skill → 读 `TASK_REGISTRY.json` → `scheduler.py --action status`
→ 任务存在且哈希一致则**接管维护，不重建**；哈希不一致则 `install` 同步；注册表不存在才全新安装。
禁止在没有检查注册表的情况下直接创建任务，否则会产生重复采集与重复推送。

### 6.8 环境不支持后台任务时

必须如实报告 `BLOCKED: 当前环境无可用调度器`，并给出等义的手动命令（每日/每周/每月/每季度各一条），
可写入用户的日历或提醒；**不得声称任务已创建**，也不得用「下次对话时顺带执行」冒充定时任务。

## 7. 合规

刷量/搬运/破解类条目只做手法与需求解读、标注平台与法律风险，不提供执行方案；
所有推荐保留来源 URL、发布时间与读取状态，取不到的字段写「未取得」。
