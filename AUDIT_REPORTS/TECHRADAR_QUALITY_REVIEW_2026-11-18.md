# TECHRADAR_QUALITY_REVIEW_2026-11-18.md — 双通道系统数据质量与可靠性增量整改

- 执行时间：2026-11-18 00:49 – 01:15
- 性质：增量整改。未重建数据库、未删除情报、未改计划任务、未改审批状态、未索取任何凭据。
- 升级前数据库：`_backup\20261118_004930\techradar.db`
  SHA256 `B89525A4321F4F1E03BE155D5EBCA461FBC9157B35E5416D8CB2C9775A69E54D`（1,380,352 B）
- 升级后数据库 SHA256 `E1041B878CBB1F86C831E9D3621A3724795C4759573E1234AEED1C8A8A1290E2`
  （变化仅来自加法式 schema：`source_registry` 新列、`provenance_quarantine`、`read_log` 空表）
- 条目数：**346 → 346（零增减）**；`integrity_check = ok`；FTS 行数 346 = 主表 346

---

## 1. 4 条数据差额的解释（已定位，非推测）

### 1.1 事实核对

| 口径 | 数值 | 来源 |
|---|---|---|
| 当前总条目 | 346 | `SELECT COUNT(*) FROM entries` |
| 历史存量（`collected_at < 2026-11-17T23:00`） | 103 | 19 点 10 条（首批 HN/GitHub）+ 22 点 93 条（ZCL 80 + 旧 daily 13） |
| 新增批次（`>= 2026-11-17T23:00`） | 243 | 103 + 243 = 346 |
| 9 个公开来源 registry 计数合计 | 239 | `SUM(items_inserted)` |
| 差额 | **4** | 见下 |

### 1.2 243 条新增按 `origin_source` 分组（求和 = 243，无遗漏）

| origin_source | 条数 |
|---|---|
| github_releases | 61 |
| rss_official | 50 |
| tg-cn-deals | 21 |
| hf_models | 20 |
| hf_daily_papers | 20 |
| arxiv | 20 |
| github_search | 13 |
| hn_frontpage | 12 |
| hf_datasets | 10 |
| linuxdo-develop | 7 |
| zhihu-search | 2 |
| rss-nodeseek | 2 |
| linuxdo-welfare | 2 |
| epic-free | 2 |
| linuxdo-resource | 1 |
| **合计** | **243** |

### 1.3 4 条差额的真实来源

`collect_zcl.py` 手动执行（2026-11-17T23:55:29）通过 `upsert_aggregated_entry()` 直接写入 4 条，
该函数**不更新 `source_registry` 计数器**，因此 registry 合计 239 少于实际新增 4 条：

| entry_id | external_key | origin_source | collected_at |
|---|---|---|---|
| 572 | zcl:42031 | tg-cn-deals（聚合上游） | 2026-11-17T23:55:29 |
| 573 | zcl:41748 | tg-cn-deals | 2026-11-17T23:55:29 |
| 574 | zcl:42034 | tg-cn-deals | 2026-11-17T23:55:29 |
| 575 | zcl:41663 | tg-cn-deals | 2026-11-17T23:55:29 |

校验：`239 + 4 = 243`；`103 + 243 = 346`。**每条记录都可解释，无 UNKNOWN 批次。**

### 1.4 顺带发现并修复的计数缺陷

`job_runs` run_id=7（daily）记录 `inserted=0`，但该次实际采集了 243 条中的大部分。
根因：`parse_counts()` 只认旧采集器的 `fetched=/picked=` 格式，新采集器输出的是中文摘要行。
修复：三个采集器新增机器可读行 `SUMMARY collected=.. inserted=.. deduped=.. failed=..`，
`lifecycle_run.parse_counts()` 优先解析该行。**修复后计数真实，不再出现"有入库但记 0"。**

---

## 2. 溯源不完整记录的分类（修正上一轮"63 条"口径）

### 2.1 口径修正

上一轮报告写"346 条中只有 283 条同时具有 origin_source 和 URL，剩余 63 条"——
该 283 是在**临时副本 305 条**规模下测得的数字，与 346 混用导致口径错误。本轮重新以真实库核对：

| 项 | 实测 |
|---|---|
| 缺 URL（`url IS NULL OR url=''`） | **0** |
| 缺 `origin_source` | **22** |
| 两者都完整 | **324** |
| 新增批次（23 点后）溯源不完整 | **0** |

### 2.2 22 条逐条分类

| source_id | 条数 | 所属时间 | 分类 |
|---|---|---|---|
| 1（Hacker News (public fallback)） | 12 | 2026-11-17T19 / 22 | 历史存量（`origin_source` 字段是后加的，旧行未回填） |
| 6（GitHub Search (public fallback)） | 10 | 2026-11-17T22 | 历史存量（同上） |

结论：**22 条全部是历史存量，不是新采集缺口，也不是聚合源误记**。
按任务要求"历史数据允许保留缺失，不要编造 URL"，本轮**不追溯回填**（它们有真实 URL，只是缺 origin 字段；
如需补齐，可按 `sources.name` 安全回填，属可选优化，见 §11）。

### 2.3 新数据入库约束（已实现）

- `_shared/skillkit/provenance.py`：校验 URL 必须 http(s) 且有 host、`origin_source` 非空、
  聚合渠道不能把自己当上游（`aggregator_as_origin`）。
- 不通过 → 写 `provenance_quarantine`、计入 `quarantined`、**不入库**（不再静默写入）。
- 连规范化都失败的记录（无 URL/无标题）同样进隔离区（原因 `normalize_failed`）。
- 历史数据不校验、不改写，查询兼容性不受影响。

---

## 3. 按需深度阅读机制（新增 `radar_read.py`）

### 3.1 状态机与触发条件

```
title_scanned ──抓取正文成功──▶ content_fetched ──真正阅读──▶ content_read ──有证据结论──▶ analyzed
```

| 状态 | 允许推进的条件 | 证据 |
|---|---|---|
| content_fetched | HTTP 200 + 内容类型为文本 + 正文 ≥200 字符 + 已写入 `extra_json.content` | `read_log(fetch, SUCCESS)` |
| content_read | 显式 `--mark-read` 且条目已有正文 | `read_log(read, SUCCESS)` |
| analyzed | 显式 `--mark-analyzed` 且必须提供 `--claim` | `read_log(analyze, SUCCESS)` + `insights` 一行 |
| archived | 人工/策略 | — |

### 3.2 入口能力

| 能力 | 实现 |
|---|---|
| 按 entry_id 阅读 | `--entry-id 123`（可重复） |
| 按搜索结果批量选候选 | `--query/--tag/--since --limit N`（复用 FTS5） |
| 内容获取验证 | 状态码、Content-Type 白名单、≥200 字符、≤2MB |
| 阅读状态记录 | `read_log` 表（stage/status/http_status/bytes/chars/error/at） |
| 失败重试 | 复用 `HttpClient` 的 3 次指数退避 |
| 来源与原始 URL 保留 | 读取 entries 原字段，不覆盖 |
| robots 合规 | 每个域名抓 `/robots.txt`，命中 `Disallow` 直接跳过并记 SKIPPED |
| dry-run | `--dry-run` 只展示将要做什么 |

### 3.3 实测（本地 fixture，未大规模访问外网）

| 用例 | 结果 |
|---|---|
| 抓取长文 → content_fetched | PASS（正文写入，read_log SUCCESS） |
| `--mark-read` → content_read | PASS |
| `--mark-analyzed --claim` → analyzed + insights | PASS（insights=1） |
| 短正文（<200 字符） | PASS（不推进，read_log FAILED，退出码 1） |
| robots Disallow | PASS（不推进，read_log SKIPPED） |
| 缺 `--claim` 的 `--mark-analyzed` | PASS（拒绝，退出码 2） |

真实库当前状态：`content_fetched 1 / title_scanned 345`——**没有批量伪造阅读状态**。

---

## 4. Source Registry 状态语义（六态分离）

新增列（加法式迁移，旧列保留）：`implementation_status`、`configuration_status`、`collection_status`、`last_checked_at`。

| 字段 | 取值 |
|---|---|
| implementation_status | IMPLEMENTED / NOT_IMPLEMENTED |
| configuration_status | CONFIGURED / UNCONFIGURED / PARTIAL / UNKNOWN |
| authorization_status | not_required / pending / approved / rejected / unknown |
| credential_status | not_required / missing / invalid / valid |
| connectivity_status | unknown / online / offline / blocked |
| collection_status | NEVER_RUN / SUCCESS / PARTIAL / FAILED / BLOCKED |
| status（派生摘要） | READY / AUTH_REQUIRED / APPROVAL_REQUIRED / DEGRADED / DISABLED / BLOCKED |

**READY 不再暗示在线或最近成功**：`STATUS_DOC` 已明确写入该语义，查询/报告必须同时看
`connectivity_status` 与 `collection_status`。未探测过的来源保持 `UNKNOWN`。

### 4.1 真实库回填后状态（`_reports/source_status_v2.json`）

| source | status | impl | config | auth | cred | conn | collect | last_ok |
|---|---|---|---|---|---|---|---|---|
| arxiv | READY | IMPLEMENTED | CONFIGURED | not_required | not_required | ONLINE | SUCCESS | 2026-11-17T23:52:52 |
| github_releases | READY | IMPLEMENTED | CONFIGURED | not_required | not_required | ONLINE | SUCCESS | 23:52:47 |
| github_search | READY | IMPLEMENTED | CONFIGURED | not_required | not_required | ONLINE | SUCCESS | 23:52:38 |
| hf_daily_papers | READY | IMPLEMENTED | CONFIGURED | not_required | not_required | ONLINE | SUCCESS | 23:52:50 |
| hf_datasets | READY | IMPLEMENTED | CONFIGURED | not_required | not_required | ONLINE | SUCCESS | 23:52:49 |
| hf_models | READY | IMPLEMENTED | CONFIGURED | not_required | not_required | ONLINE | SUCCESS | 23:52:48 |
| hn_frontpage | READY | IMPLEMENTED | CONFIGURED | not_required | not_required | ONLINE | SUCCESS | 23:52:36 |
| radar_zcl | READY | IMPLEMENTED | CONFIGURED | not_required | not_required | ONLINE | SUCCESS | 23:53:10 |
| rss_official | READY | IMPLEMENTED | CONFIGURED | not_required | not_required | ONLINE | SUCCESS | 23:53:00 |
| folo | AUTH_REQUIRED | IMPLEMENTED | UNCONFIGURED | granted | invalid | unknown | BLOCKED | - |
| reddit | AUTH_REQUIRED | IMPLEMENTED | UNCONFIGURED | **pending** | invalid | unauthorized | BLOCKED | - |

Reddit 的 `status` 显示 AUTH_REQUIRED（最近一次无效凭据），但 `authorization_status=pending` 独立可见——
**审批状态没有被凭据状态掩盖**，符合"三态不得混为一谈"。

### 4.2 状态回填

`backfill_status()` 只依据已有证据修正占位值（有 `last_success_at` → SUCCESS/ONLINE/CONFIGURED；
认证源凭据缺失 → UNCONFIGURED/BLOCKED），幂等且不覆盖已有真实状态。

---

## 5. FTS5 CRUD 与检索一致性（全部在临时库）

| 用例 | 结果 |
|---|---|
| 新增记录 → FTS 同步（英文/中文） | PASS（EN=1, CN=1） |
| 更新正文 → 旧词消失、新词出现 | PASS（old=0, new=1） |
| 删除记录 → 无孤儿索引 | PASS（orphan=0） |
| 事务失败 → 主表与索引同时回滚 | PASS（entry=0, fts=0） |
| LIKE 降级 | PASS（engine=like，命中 1） |
| 中文检索（前缀） | PASS |
| 模型名检索（Qwen3 / Llama.cpp） | PASS |
| 去重 / 聚合入库 | PASS（R3 合法记录入库、非法隔离） |

实现改动：`_fts_index_entry(commit=False)` 默认加入调用方事务，`add_entry`/`store_content`
在事务提交后再统一提交索引，**保证"主表写入 + 索引写入"原子性**。

---

## 6. relations 真实能力边界

当前 `relations=0`，这是**允许且诚实**的初始状态。可用的关联方式只有五类：

| 类型 | 依据 | 可靠性 | 当前是否有数据 |
|---|---|---|---|
| 关键词关联 | FTS5/LIKE 词面命中 | 弱（同词不同义会误召） | 有（346 条可检索） |
| 标签关联 | tags / entry_tags | 中 | 有（48 标签 / 639 关联） |
| 同项目跨来源关联 | canonical_key | 强 | 有（`canonical_groups` 可查） |
| 显式关系 | relations（需 note 证据） | 强 | **0（无人工确认）** |
| 来源共现 | 同 origin/aggregator | 弱 | 有（可直接 SQL 统计） |

SKILL.md §4.4 已明确写入：**不得把关键词共现宣传成知识图谱或因果关系**；
`relations=0` 不视为缺陷，只有可核验证据才允许 `link_relation()` 写入。

---

## 7. 四种维护任务验证

### 7.1 真实计划任务（只读检查，未改触发时间）

| 任务 | 状态 | 下一步运行 |
|---|---|---|
| TechRadar_Daily | Ready | 2026-11-18 07:30 |
| TechRadar_Weekly | Ready | 2026-11-22 08:00 |
| TechRadar_Monthly | Ready | 2026-12-01 09:00 |
| TechRadar_Quarterly | Ready | 2027-01-01 10:00 |

任务注册表 4 条、`config_hash` 齐全；本轮未创建/修改/删除任何任务（幂等性未破坏）。

### 7.2 副本上的四周期执行

| 周期 | 结果 | 证据 |
|---|---|---|
| daily | PASS（dry-run） | exit=0，job_runs 新增 |
| weekly | PASS（dry-run） | exit=0，清理计划生成 |
| monthly | PASS（dry-run + 备份） | exit=0，备份目录与 manifest |
| quarterly | PASS | exit=0，审计报告 |

### 7.3 备份与恢复

- 备份产物：`_backup/lifecycle/*/techradar.db`（16 个历史备份）
- 最新备份可打开，`entries=346`、`integrity_check=ok` → **恢复能力可用**
- 清理保护：`apply_purge=false`，四周期全部 dry-run，未删除任何数据

### 7.4 状态标注

- daily：有历史真实采集记录（run 6/7），本轮副本复跑 PASS → **PASS**
- weekly / monthly / quarterly：计划任务尚无自然触发记录，本轮仅在副本验证逻辑 → **PARTIAL**（不冒充线上 PASS）

---

## 8. Folo 接口依据与许可证修正

| 项 | 修正后表述 |
|---|---|
| 归属 | 接口依据为**第三方开源项目** `folo-mcp`（作者 Stephen Zhou / hyoban），**不是 Folo 官方发布的 MCP**，也不是官方文档化 API |
| 仓库 | https://github.com/hyoban/folo-mcp |
| 版本 | 1.0.0（npm `folo-mcp`） |
| 许可证 | MIT |
| 参考制品 | `folo-mcp-1.0.0.tgz`，SHA256 `812CE7D8F0F70CA8B65D0EF6722E52BA5C70F53D9945A73D1DA818473E9510C1`（3,291 B） |
| 端点性质 | 通过浏览器 Cookie 会话访问 `api.follow.is` 内部接口，属第三方**接口观察**，非官方稳定契约 |
| 兼容风险 | 随 Folo 前端升级可能失效；代码已做防御式解析（`_envelope` / `_entry_to_record`） |
| 已修正位置 | `collect_folo.py` 模块文档、`03_techradar/SKILL.md` §2.2、本报告 |

安全说明：
- Folo Cookie 只允许用户在本地 `.env` 填写，**不得发送给 AI 助手**，不写入日志/报告/数据库。
- `.env` 已被 `.gitignore` 排除（`.env`、`.env.*`、`*.pem`、`*.key`、`*.db`、`_backup/`）。
- **无效令牌被拒绝 ≠ 有效凭据采集成功**：B2/B5 仍标 NOT_TESTED，未冒充。

Reddit 保持官方审批流程：`developers.reddit.com/app-registration`，不绕过、不伪造 UA、不用 RSS 镜像。

---

## 9. 新增与修改文件

**新增（4）**

| 文件 | 作用 |
|---|---|
| `_shared/skillkit/provenance.py` | 入库前溯源校验 + 隔离区 |
| `03_techradar/scripts/radar_read.py` | 按需深度阅读入口 |
| `tests/test_quality_review.py` | R1–R10/R12 共 50 项断言 |
| `_reports/source_status_v2.json` | 六态状态清单证据 |

**修改（8，均已备份）**

| 文件 | 改动 |
|---|---|
| `_shared/skillkit/sources.py` | 新增三态列、`backfill_status`、状态文档 |
| `_shared/skillkit/pipeline.py` | 入库强制溯源校验、状态写全、`quarantined` 计数 |
| `_shared/skillkit/inteldb.py` | FTS 与主表同事务、`store_content`、`mark_read_state_by_id`、`read_log` |
| `03_techradar/scripts/collect_public_suite.py` | 输出 `SUMMARY` 机器可读行 |
| `03_techradar/scripts/collect_folo.py` | 归属/许可证/兼容风险修正 + SUMMARY |
| `03_techradar/scripts/collect_reddit.py` | 输出 SUMMARY |
| `03_techradar/scripts/lifecycle_run.py` | `parse_counts` 优先解析 SUMMARY |
| `03_techradar/scripts/source_status.py` | 展示六态列 |
| `03_techradar/SKILL.md` | §2.3 六态、§4.3 深度阅读、§4.4 关联边界 |
| `CAPABILITY_REGISTRY.yaml` / `README.md` / `CHANGELOG.md` | C18、计数与变更记录 |

---

## 10. 真实数据库保护结果

| 项 | 结果 |
|---|---|
| 条目数 | 346 → 346（零增减） |
| 真实情报 | 未删除任何一条 |
| 明文数据 | 未改写；仅加法式 schema（新列/空表） |
| `integrity_check` | ok（升级前后各一次） |
| FTS 行数 | 346 = 主表 346（无孤儿） |
| 计划任务 | 4 个原样保留，触发时间未变 |
| 写入测试 | 全部在 `%TEMP%` 副本执行；真实库无测试数据插入 |
| 凭据 | 未读取、未打印、未修改、未索取 |
| 外部副作用 | 仅公开 HTTP GET（HN/GitHub/HF/arXiv/RSS/资源雷达/本地 fixture），无发布、无付费、无登录 |

---

## 11. 仍需人工处理

| # | 事项 | 状态 | 说明 |
|---|---|---|---|
| 1 | Folo 会话令牌 | AUTH_REQUIRED | 用户在本地 `.env` 填 `FOLO_SESSION_TOKEN`（勿发送给 AI） |
| 2 | Reddit 官方审批 + 凭据 | APPROVAL_REQUIRED / pending | app-registration 与访问审批；代码不绕过 |
| 3 | 22 条历史缺 `origin_source` | 可保留 | 有真实 URL；如需要可按 `sources.name` 安全回填（可选，不编造） |
| 4 | `relations=0` | 可保留 | 需人工确认的真实关联证据后才写入 |
| 5 | weekly/monthly/quarterly 线上证据 | PARTIAL | 等 2026-11-22 / 12-01 / 2027-01-01 自然触发后回查 |
| 6 | 真实库深度阅读 | NOT_TESTED | 本轮用本地 fixture 验证；真实条目按需执行 `radar_read.py` |

---

## 12. 测试命令、退出码与产物

| 套件 | 命令 | 退出码 | 产物/说明 |
|---|---|---|---|
| 质量复核（新） | `python tests\test_quality_review.py` | 0 | R1–R10/R12 共 50 项断言 |
| 双通道 | `python tests\test_dual_channel.py` | 0 | A/B/C/D 全通过 |
| 契约 | `python tests\test_skillkit_contract.py` | 0 | — |
| 情报库 | `python tests\test_techradar.py` | 0 | — |
| 注册表 | `python tests\test_registry.py` | 0 | 18 项能力 |
| 视频 | `python tests\test_video_pipeline.py` | 0 | — |
| ZCL 集成 | `python tests\test_zcl_integration.py` | 0 | 13 PASS |
| 生命周期 | `python tests\test_lifecycle.py` | 0 | — |
| 整改 | `python tests\test_remediation.py` | 0 | — |
| 触发 | `python tests\test_triggers.py` | 0 | 80 用例静态检查 |
| 协同场景 | `python tests\test_scenarios.py` | 0 | A/B/C |
| 来源状态 | `python 03_techradar\scripts\source_status.py --json _reports\source_status_v2.json` | 0 | 六态清单 |
| 深度阅读（fixture） | `python 03_techradar\scripts\radar_read.py --db <副本> --entry-id N --fetch` | 0 | read_log 证据 |

**SHA256**
- 升级前 DB：`B89525A4321F4F1E03BE155D5EBCA461FBC9157B35E5416D8CB2C9775A69E54D`
- 升级后 DB：`E1041B878CBB1F86C831E9D3621A3724795C4759573E1234AEED1C8A8A1290E2`
- 备份清单：`_backup\20261118_004930\manifest.csv`（11 项，含 10 个源文件 + DB）
- folo-mcp 参考制品：`812CE7D8F0F70CA8B65D0EF6722E52BA5C70F53D9945A73D1DA818473E9510C1`

**结论**：11 套测试全部退出码 0；真实库零删除、完整性 ok；4 条差额与 22 条溯源缺失均已定位并可解释；
深度阅读、六态注册表、FTS 事务一致性已补齐并有实测证据；需要凭据与审批的部分如实标记，未冒充。
