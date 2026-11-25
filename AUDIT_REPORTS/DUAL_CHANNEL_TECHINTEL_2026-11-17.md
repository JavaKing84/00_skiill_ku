# DUAL_CHANNEL_TECHINTEL_2026-11-17.md — TechRadar 双通道技术情报采集体系交付报告

- 执行时间：2026-11-17 23:30 – 2026-11-18 00:15
- 目标库：`D:\00_skiill_ku`（本次为增量升级，未重建数据库、未删除既有情报、未改既有计划任务）
- 备份：`_backup\20261117_2352xx\techradar_pre_origin_fix.db`（溯源修正前快照，含 SHA256）

---

## 1. 双通道架构

```
                      ┌──────────────── 通道 A：公开（零凭证）────────────────┐
                      │ HN · GitHub 搜索/Release · HF 模型/数据集/论文 · arXiv │
                      │ 官方博客 RSS/Atom · 资源雷达公开只读 API              │
                      └───────────────────────┬───────────────────────────────┘
                                              │
┌──────────── 通道 B：认证 ────────────┐       │
│ Folo（Cookie 会话）· Reddit（OAuth） │───────┤
└───────────────┬─────────────────────┘       │
                ▼                             ▼
        skillkit.pipeline（统一管线）：解析 → 标准化 → 质量校验 → 去重 → 入库
                                              │
                    skillkit.sources（Source Registry：状态/授权/凭据/连通/计数）
                                              │
                        SQLite（schema v3 + entries_fts）→ FTS5 索引
                                              │
                          radar_query.py（FTS5 优先，LIKE 降级）
```

**两通道独立运行、统一入库、统一检索、互不阻塞**：任一来源失败只把该来源标记为 `DEGRADED`，调度器继续执行其余来源；认证通道完全不可用时，通道 A 不受影响。

## 2. 新增与修改文件清单

**新增（14）**

| 文件 | 作用 |
|---|---|
| `_shared/skillkit/http.py` | 共享 HTTP 层：UA/超时/退避重试/限速/脱敏错误 |
| `_shared/skillkit/sources.py` | Source Registry：状态机 + 计数 + 三态分列 |
| `_shared/skillkit/pipeline.py` | 统一管线：标准化、去重、入库、故障隔离 |
| `03_techradar/scripts/public_sources.py` | 通道 A 的 9 个公开源适配器 |
| `03_techradar/scripts/collect_public_suite.py` | 通道 A 编排器 |
| `03_techradar/scripts/collect_folo.py` | 通道 B-1 Folo 认证适配器 |
| `03_techradar/scripts/collect_reddit.py` | 通道 B-2 Reddit OAuth 适配器 |
| `03_techradar/scripts/source_status.py` | 来源注册表巡检与状态清单 |
| `.env.example` | 凭据模板（`.env` 已被 `.gitignore` 排除） |
| `.gitignore` | 排除 `.env` / `*.db` / `_backup/` / `.venv/` |
| `tests/test_dual_channel.py` | 双通道验收（A1–A4、B1–B5、C1–C3、D1–D2） |
| `03_techradar/data/folo_checkpoint.json`、`reddit_checkpoint.json` | 增量水位（运行时生成） |
| `_reports/source_status.json`、`channel_a_run1.json` | 运行证据 |

**修改（7）**

| 文件 | 改动 |
|---|---|
| `_shared/skillkit/inteldb.py` | `add_entry` 支持 `origin_source/aggregator/tags/external_key`；`upsert_aggregated_entry` 冲突时按 `content_hash` 归并；FTS 索引联动去重 |
| `_shared/skillkit/search.py` | `index_entry` 先删后插（同一 entry_id 只留一行）；新增 `dedupe_fts` |
| `_shared/skillkit/pipeline.py` | `origin_extra_key`（聚合源记录真实上游）、成功时清空 `last_error` |
| `03_techradar/scripts/lifecycle_run.py` | 每日任务的采集器改为 `collect_public_suite` + `collect_folo` + `collect_reddit`；退出码 3 记为 BLOCKED 不算失败 |
| `03_techradar/SKILL.md` | 新增 §2.2 双通道采集体系、§2.3 统一 Source Registry |
| `CAPABILITY_REGISTRY.yaml` | 新增 C17 双通道采集（status=PARTIAL） |
| `README.md` / `CHANGELOG.md` | 能力数 16→17、变更记录 |

## 3. 数据源状态清单（source_registry 实测）

| source_id | 通道 | 状态 | 授权 | 凭据 | 连通 | 抓取 | 入库 | 去重 |
|---|---|---|---|---|---|---|---|---|
| hn_frontpage | public | READY | not_required | not_required | unknown | 35 | 12 | 23 |
| github_search | public | READY | not_required | not_required | unknown | 35 | 13 | 22 |
| github_releases | public | READY | not_required | not_required | unknown | 120 | 61 | 59 |
| hf_models | public | READY | not_required | not_required | unknown | 35 | 20 | 15 |
| hf_datasets | public | READY | not_required | not_required | unknown | 17 | 10 | 7 |
| hf_daily_papers | public | READY | not_required | not_required | unknown | 35 | 20 | 15 |
| arxiv | public | READY | not_required | not_required | unknown | 35 | 20 | 15 |
| rss_official | public | READY | not_required | not_required | unknown | 100 | 50 | 50 |
| radar_zcl | public | READY | not_required | not_required | unknown | 35 | 33 | 2 |
| **folo** | authenticated | **AUTH_REQUIRED** | granted | missing/invalid | unknown | 0 | 0 | 0 |
| **reddit** | authenticated | **APPROVAL_REQUIRED** | pending | missing/invalid | unauthorized | 0 | 0 | 0 |

- 公开通道 9/9 READY，**未被误标 BLOCKED**；两个认证源分别标记 AUTH_REQUIRED / APPROVAL_REQUIRED。
- Reddit 公开 JSON 端点实测 403、OAuth 令牌端点实测 401（无凭据）→ 说明确实必须走官方授权，不能绕。

## 4. 实际采集数量与数据库证据

| 项 | 数值 |
|---|---|
| 起始条目（整改前） | 103 |
| 当前条目 | **346**（新增 243） |
| FTS5 索引行 | 346（与主表一致） |
| 数据库大小 | 1,380,352 B |
| `PRAGMA integrity_check` | ok |
| tags / entry_tags | 48 / 639 |
| relations | 0（能力已实现并测试，尚无真实人工关联） |
| read_state | content_fetched 1 / title_scanned 345（只有真正取回正文的条目才推进，未批量伪造） |
| 聚合 vs 直采 | aggregator=radar.zichuanlan.top 114 条；直采 232 条 |

真实检索证据（`radar_query.py --scenario ai-robot`，engine=fts5）：命中 `llama.cpp b12475`（跨源复现 x11）、`ScaleVLA: Scaling Vision-Language-Action Models`、`JEPA4R: Embodied JEPA World Models`、`SALA: Semantically Aligned Latent Actions`、`华为云开源昇腾原生具身世界模型 CloudRobo-WM1.2`、`Build a Robot Pick-and-Place Simulation`。

## 5. 认证接入实现细节（非占位）

### Folo
- 真实 Base：`https://api.follow.is`；认证：Cookie `__Secure-better-auth.session_token=<token>;` + 浏览器 UA。
- 接口：`GET /subscriptions`（订阅列表）、`POST /entries`（`view/feedId/limit/publishedAfter/withContent`）、`GET /feeds`。
  依据：官方 MCP 实现 `folo-mcp`（MIT，github.com/hyoban/folo-mcp）的真实请求封装，已解包核对源码。
- 增量：按 feed 维护 `publishedAfter` 水位（`data/folo_checkpoint.json`），失败不前移。
- 现状：凭据缺失 → `AUTH_REQUIRED` 并输出获取与配置指引；用无效令牌发起**真实请求**被正确拒绝（exit=2），证明认证路径已打通到线上端点。

### Reddit
- 官方流程：`POST https://www.reddit.com/api/v1/access_token`（HTTP Basic + `grant_type=client_credentials`）→ Bearer；
  访问 `https://oauth.reddit.com/r/<sub>/new?limit&after`；真实 User-Agent（`linux:techradar-intel:1.0 …`）。
- 分页：`after` 游标；限流：429 退避重试（`HttpClient` 内置）；增量：按 sub 记录最新时间水位。
- 审批：`APPROVAL_REQUIRED` 与 `credential_status` / `connectivity_status` **三列分列记录**，互不替代。
- 合规：未使用伪造 UA、未授权接口、RSS 镜像或任何绕过访问控制的手段。
- 现状：无凭据 → `APPROVAL_REQUIRED` + 审批指引；无效凭据 → 真实 401 → 正确识别为 AUTH_REQUIRED（exit=3）。

## 6. 测试证据（命令 / 退出码 / 结果）

| 测试 | 命令 | 退出码 | 结果 |
|---|---|---|---|
| A1 零凭证公开采集 | `collect_public_suite.py --db <副本> --limit 10` | 0 | PASS（9/9 来源 READY） |
| A2 多来源真实采集 | 同上 | 0 | PASS（9 个来源各自有数据） |
| A3 公开数据写入 SQLite | 同上 | 0 | PASS（副本新增 9 条；真实库累计 346 条） |
| A4 FTS5 检索新入库数据 | `radar_query.py --text "llm OR model OR robot"` | 0 | PASS（hits=5, engine=fts5） |
| B1 Folo 正式认证流程 | 读码核对 + 缺凭据运行 | 3 | PASS（接口/端点/配置指引齐备） |
| B2 合法 Folo 凭据后真实采集 | `collect_folo.py` + 无效令牌 | 2 | **NOT_TESTED**（无用户凭据；认证路径已用真实端点验证） |
| B3 Reddit OAuth 适配器 | 读码核对 + 缺凭据运行 | 3 | PASS（官方端点 + 审批流程） |
| B4 审批/凭据状态识别 | `source_status.py` + 无效凭据 | 3 | PASS（三态分列正确） |
| B5 授权后 Reddit 真实采集 | — | — | **NOT_TESTED**（需官方 app-registration 与访问审批） |
| C1 Folo 故障不影响公开 | 先后运行 | 2 / 0 | PASS |
| C2 Reddit 故障不影响公开 | 先后运行 | 3 / 0 | PASS |
| C3 两认证通道同时失败 | 三者依次运行 | 3 / 3 / 0 | PASS（公开通道仍 PASS） |
| D1 去重/溯源/索引/完整性 | 二次采集 + 校验 | 0 | PASS（deduped=175；FTS 346=346；integrity ok；283 条带 origin+url） |
| D2 原有功能与计划任务回归 | 9 套历史测试 | 0×9 | PASS；4 个计划任务原样保留 |

整套回归：**10 套测试全部退出码 0**（契约 / 情报库 / 注册表 / 视频 / ZCL 集成 / 生命周期 / 整改 / 触发 / 协同场景 / 双通道）。

本轮由测试抓出并修复的真实缺陷：`http.py` 传 `json_body` 给 requests、`add_entry` 未持久化 external_key 导致唯一约束冲突、
Reddit UA 含非 latin-1 字符、FTS 重复索引行（362>346）、聚合源 origin_source 记录成渠道 id、状态残留旧错误。

## 7. 安全与凭据管理

- `.env.example` 提供模板；`.env` 由 `.gitignore` 排除；仓库不含真实密钥。
- 凭据只从环境变量/`.env` 读取；错误信息经 `loggingx.mask` 脱敏；报告与日志不含 Token/Cookie/Secret。
- 失效凭据可重新认证：补齐 `.env` 后重跑即恢复；凭据无效会被标为 `invalid` 并给出指引。
- 无凭据时**不伪造成功**：通道 B 直接 `BLOCKED`（退出码 3），公开通道照常。

## 8. 需要你提供的凭据与配置步骤

| # | 事项 | 步骤 | 解锁 |
|---|---|---|---|
| 1 | Folo | 登录 app.folo.is → DevTools → Network → 任一请求 Cookie → 复制 `__Secure-better-auth.session_token` 的值 → 写入 `.env` 的 `FOLO_SESSION_TOKEN=` | 通道 B-1 |
| 2 | Reddit | 在 developers.reddit.com/app-registration 注册 script 应用并等待访问审批 → 写入 `.env` 的 `REDDIT_CLIENT_ID=` / `REDDIT_CLIENT_SECRET=` | 通道 B-2 |
| 3 | （可选）GitHub 提额 | `.env` 的 `GITHUB_TOKEN=` | GitHub 限额 10→5000/时 |

```powershell
Copy-Item .env.example .env   # 然后填入上述值
python 03_techradar\scripts\collect_folo.py   # 验证
python 03_techradar\scripts\collect_reddit.py # 验证
python 03_techradar\scripts\source_status.py  # 查看状态是否转为 READY
```

## 9. 剩余外部审批事项

1. **Reddit 官方访问审批**：必须由账号主体提交，代码无法代劳（当前状态 APPROVAL_REQUIRED / authorization_status=pending）。
2. **Reddit app-registration**：2026 年起需在开发者后台完成注册。
3. **Folo 会话令牌**：需要你本人登录态，任何自动化获取都属越权，故只提供手动获取指引。

## 10. 保留与未破坏项（实测）

- 原有 103 条情报全部在位（现 346 条 = 103 + 243 新增），零删除。
- schema v3 未变；新增仅为 `source_registry` 表与 `entries_fts` 虚表（及索引辅助表）。
- FTS5 检索、LIKE 降级、幂等去重、原始链接与溯源、四个计划任务、三条全局路由规则全部保留并通过回归。
- 未产生费用、未真实发布、未修改任何凭据、未改动活动客户端全局配置。
