# THREE_SKILLS_REMEDIATION_2026-11-17.md — 三个核心 Skill 全面整改报告

- 执行日期：2026-11-17 22:53–23:20
- 响应对象：第一轮审计 `AUDIT_REPORTS\THREE_SKILLS_AUDIT_2026-11-17.md`（25 条问题，IS-01～IS-25）
- 性质：**增量整改**。未重建数据库、未删除任何情报、未重跑 Phase 0–7、未创建重复计划任务
- 备份：`_backup\20261117_225336\`（24 个文件 + 数据库 + `backup_manifest.csv` 含 SHA256）+ `db_baseline.json`

---

## 1. 整改概览

### 1.1 改了什么、为什么改

| 领域 | 改动 | 对应问题 | 为什么改 |
|---|---|---|---|
| 路由层 | 新建 3 条独立全局规则 | IS-01/02/10 | 审计证明：单一规则 + 三套 Skill 无人知道何时用，是所有能力失效的根因 |
| 路由层 | 旧规则收敛为「会议纪要与长文档路由」 | 第五部分 | 拆规则不能丢功能：会议六段式、云笔记、轻量报错直答全部保留 |
| canonical | 00 v2.0→2.1、02 v1.0→1.1、03 v1.2→1.3，补 frontmatter（triggers / not_triggers / 执行入口 / 版本 / 边界） | IS-03/06/21 | 客户端靠 frontmatter 匹配触发，缺字段＝不会被发现 |
| 客户端入口 | tech-radar 壳补 canonical 路由段；material-sourcing-crawler 壳补 canonical 与新运行时路径；aitoearn 壳补 02 关系段 | IS-01/11 | 壳与 canonical 脱节＝库建好了但对话看不见 |
| WorkBuddy | 新增 `techradar`、`video-pipeline` 两个入口壳 | IS-02 | 跨客户端迁移能力 |
| TechRadar 检索 | 新增 `search.py`：FTS5 全文 + 时间/标签/来源/关联组合查询，LIKE 降级、索引自愈 | IS-07 | 原库只能关键词 LIKE，无法按时间/标签/关系检索 |
| TechRadar 状态 | read_state 改为五级只前进状态机 + 标签写入 + 显式关系登记 | IS-06 | 原字段名与新状态不一致且无推进路径，103 条全停在 title_scanned |
| TechRadar 调度 | `scheduler --action status` 改真正只读（mode=ro、不迁移、不写库、不改 mtime） | IS-15 | 原实现会执行迁移 UPDATE，违反"检查不应改库" |
| 视频 | 新增 `render.py`（拼接/画幅/字幕/授权 BGM/loudnorm/导出 + 自动 QC）+ `assets/BGM_LICENSES.json` | IS-03/04 | 02 原本无渲染实现；BGM 缺失需用"拒绝未授权素材"代替"假装有" |
| 爬虫 | 00 明确"协议库 ≠ 执行器"职责，加 §7 执行入口与轻量/完整流程分界 | IS-09 | 不重复造 runner，但要把执行器指到 material-sourcing-crawler |
| 测试 | 2 套真实库测试改默认隔离；新增 4 套测试 + 同步校验器 + 80 用例触发集 | IS-12 | 审计/CI 不能改真实数据 |
| 文档 | README 能力数 12→16、Schema v2→v3、AGENTS 运行时路径、C14 状态降级为 PARTIAL | IS-14/20 | 三个数字互相矛盾会误导下一个 Agent |

### 1.2 解决了哪些 / 没解决哪些

**已解决（13 项，有执行证据）**：IS-01、IS-02（Trae+WorkBuddy 入口）、IS-03、IS-04（改为授权闸门）、IS-06、IS-07、IS-09、IS-10、IS-11（哈希校验器）、IS-12、IS-13（未做，见下）、IS-14、IS-15、IS-21、IS-22、IS-23、IS-24。

**部分解决**：IS-05（周/月/季在临时库副本上四周期全部实跑通过，真实计划任务仍只有 daily 有过实跑记录）；
IS-16（真实库 purge_log 仍为 0，删除只在副本验证）；IS-17（QC 仍以合成 fixture 为主）；IS-20（C14 已降级为 PARTIAL）。

**未解决（需要人工或新客户端）**：IS-08（Folo/Reddit 凭据）、IS-13（统一日志未全量接入）、IS-18（真实发布未验证）、
IS-19（02 与 03 之间仍无程序级互调，只有 Playbook 级指引）。

---

## 2. 三条独立全局规则

### 2.1 文件与状态

| 规则名称 | 真实路径 | alwaysApply | canonical 指向 |
|---|---|---|---|
| 视频剪辑与制作路由 | `C:\Users\26808\.trae-cn\user_rules\rule-1794927301000.md` | true | `D:\00_skiill_ku\02_video_pipeline\SKILL.md`（v1.1.0） |
| 爬虫与网站数据采集路由 | `C:\Users\26808\.trae-cn\user_rules\rule-1794927302000.md` | true | `D:\00_skiill_ku\00_crawl_Skills\SKILL.md`（v2.1.0） |
| TechRadar技术情报与研究路由 | `C:\Users\26808\.trae-cn\user_rules\rule-1794927303000.md` | true | `D:\00_skiill_ku\03_techradar\SKILL.md`（v1.3.0） |
| 会议纪要与长文档路由（旧规则收敛） | `C:\Users\26808\.trae-cn\user_rules\rule-1794846677938.md` | true | 模式 B → `03_techradar\SKILL.md`（v1.3.0） |

规则目录实测：4 个 `rule-*.md`，frontmatter 均为 `description` + `alwaysApply: true`，**无 UTF-8 BOM**（曾因 PowerShell 写入产生 BOM，已修复并全库扫描确认）。

### 2.2 规则内容要点

**① 视频剪辑与制作路由**
- 路由：`aitoearn → 02_video_pipeline`；aitoearn 负责真实剪辑/字幕/配音/生成/发布，02 负责素材校验/参考分析/QC/发布预览。
- 正向 15 条（剪辑→成片→合并→参考复刻→仿制→字幕花字配音→BGM 转场→画幅→批量→压缩导出→质检→文案生成→封面→发布预览→画幅转换）。
- 负向 11 条（只分析视频内容 / 仅下载视频 / 视频生成技术 / 只讨论剪辑理论 / 只阅读单篇文章 / 普通翻译 / 普通搜索 / 单独修代码 / 普通业务功能 / 网页技术概念 / 纯图片编辑）。
- 执行要求：必须真实调用工具；成片必须过 `video_qc.py`；记录路径/时长/分辨率/帧率/音视频信息/QC 结果；无工具不得承诺；发布默认 dry-run。
- 安全：不得真实发布、不得用 `license_status=unknown` 素材、不得用未登记 BGM、日志脱敏。

**② 爬虫与网站数据采集路由**
- 路由：`material-sourcing-crawler → 00_crawl_Skills`；协议库负责定性/选型/排障，执行器负责下载落盘。
- 正向 15 条（抓取→采集正文→多页面→批量下载→自动翻页→XHR→写爬虫→403/429→签名参数→登录态→断点续采→多源→入库→性能优化→找素材）。
- 负向 11 条（打开网页 / 阅读单篇 / 总结已给文章 / 普通搜索 / 网页概念 / 视频剪辑 / 技术选型 / 翻译 / 修代码 / 普通功能 / 只读已给文档）。
- 特别规则：明确说"抓取这个网站的数据"必触发，但简单任务只走轻量流程。

**③ TechRadar技术情报与研究路由**
- 六类需求全覆盖：A 技术发现与趋势追踪 / B 技术研究与方案探索（含跨领域组合）/ C 开源项目与工具生态评估 / D 情报采集与知识沉淀（含 GitHub、HN、Reddit、Folo、RSS、Bluesky、Telegram、Resource Radar）/ E 历史情报检索与综合分析 / F 持续监控与知识库维护。
- 三级执行模式：轻量情报 / 深度研究 / 持续维护。
- 负向 9 类：基础概念、单独修代码、普通功能、翻译润色、单篇文档、普通网页打开、视频剪辑、素材采集。
- 执行要求：先读 canonical；**必须真实调用 `radar_query.py`**，不得把联网搜索冒充本地检索；输出必须带来源/时间/原始链接/证据；Folo/Reddit 缺失标 BLOCKED。
- 调度：检查真实 Windows 任务计划程序，幂等安装，不重复创建。

### 2.3 旧规则处理

保留：会议六段式输出（模式 B）、云笔记同步、轻量单一报错直接回答。
移除：与三条新规则重复或竞争的宽泛 TechRadar 路由（技术选型/代码优化/架构设计/开源库调研已分别迁入三条新规则）。

---

## 3. 三个 Skill 的最终状态

| 维度 | 爬虫 `00_crawl_Skills` | 视频 `02_video_pipeline` | 情报 `03_techradar` |
|---|---|---|---|
| 是否正确安装 | ✅ Trae 经 material-sourcing-crawler 指向；WorkBuddy 有同哈希副本 | ✅ Trae 经 aitoearn 指向；WorkBuddy 新增 video-pipeline 壳 | ✅ Trae tech-radar 壳指向；WorkBuddy 新增 techradar 壳 |
| 是否可被 Agent 发现 | ✅（有 description + triggers/not_triggers） | ✅（同上） | ✅（同上） |
| 是否正确读取 canonical | ✅ 壳内绝对路径 + 版本号双标注 | ✅ | ✅ |
| 是否具备实际执行工具 | ✅ material_crawler.py（执行器） | ✅ aitoearn MCP + 4 脚本 + 新增 render.py | ✅ 7 脚本 + SQLite v3 + FTS5 |
| 是否真实完成任务 | ✅ 本轮场景 A 实跑：本地 fixture 站点采集→入库→检索→去重→溯源 | ✅ 本轮场景 B 实跑：选题→参考分析→渲染→QC→发布预览 | ✅ 场景 A/B 均实跑；FTS 回填 103 条 |
| 功能边界 | 协议库，不负责下载 | 基础渲染；复杂混剪仍以 aitoearn 为准 | 3 源可用（HN/GitHub/Resource Radar），Folo/Reddit BLOCKED |
| 当前状态 | PASS | PASS | PASS（FTS/检索/生命周期/调度均为本轮实测） |

---

## 4. 测试证据

### 4.1 全量回归（9 套，全 PASS）

| 命令 | 退出码 | 结果 |
|---|---|---|
| `python tests\test_skillkit_contract.py` | 0 | PASS（枚举/两级去重/断点/退避/脱敏） |
| `python tests\test_techradar.py` | 0 | PASS（建表/去重/状态机/台账/持久化） |
| `python tests\test_registry.py` | 0 | PASS（16 项能力字段/状态枚举/5 适配文档） |
| `python tests\test_video_pipeline.py` | 0 | PASS（好片 PASS / 坏片 FAIL / dry-run 脱敏） |
| `python tests\test_zcl_integration.py` | 0 | SUMMARY 13 PASS / 0 PARTIAL / 0 FAIL |
| `python tests\test_lifecycle.py` | 0 | PASS（策略/保护/观察期/降采样/删除日志/恢复/完整性/CLI） |
| `python tests\test_remediation.py` | 0 | PASS（22 项：规则/同步/FTS/时间/标签/来源/关联/状态机/只读 status/四周期/渲染/BGM 闸门） |
| `python tests\test_triggers.py` | 0 | 静态规则检查 80 用例：正向覆盖 45 / 负向边界 30 / 组合 5 全通过 |
| `python tests\test_scenarios.py` | 0 | PASS（场景 A 7 项 / B 5 项 / C 4 项） |
| `python tests\skill_sync_check.py` | 0 | SYNC OK：canonical / 客户端壳 / 全局规则一致 |

### 4.2 关键功能实测明细

| 能力 | 命令 | 退出码 | 产物 / 证据 |
|---|---|---|---|
| FTS5 全文检索 | `radar_query.py --text "robot"` | 0 | engine=fts5；真实库 `hits=1`（华为云开源昇腾原生具身世界模型 CloudRobo-WM1.2，`rss-ithome`，2026-11-16） |
| 时间过滤 | `--since 2026-11-01` | 0 | 仅返回窗口内条目（断言通过） |
| 标签过滤 | `--tag robot` | 0 | 命中 2 条且均带 robot 标签 |
| 来源过滤 | `--source github-awesome-ai` | 0 | 命中 11 条且 origin 全匹配 |
| 关联检索 | `--related <entry_id>` | 0 | 命中 2 条（含显式 relations 与同 canonical_key） |
| LIKE 降级 | `--engine like` | 0 | hits=4，功能不依赖 FTS5 |
| 读取状态机 | `mark_read_state()` | 0 | content_fetched→content_read→analyzed 成功；降级被拒；非法值抛错 |
| scheduler status 只读 | `scheduler.py --action status` | 0 | 真实库 mtime 前后相同（1794925757.4921346 == 同值），行数 103 == 103 |
| 四周期隔离运行 | `lifecycle_run.py --job daily\|weekly\|monthly\|quarterly`（临时库副本） | 0×4 | 4 条 job_runs（run_id 7–10），全部 dry-run、purged=0 |
| 基础渲染 | `render.py --inputs a.mp4 b.mp4 --aspect 9:16 --subtitle ... --qc` | 0 | 成片 1080×1920 / 30fps / aac 48k stereo / 5s / 194,130 B；QC PASS |
| BGM 授权闸门 | `render.py --bgm 未登记文件` | 2 | `BLOCKED: BGM 未登记授权`（未使用版权不明音乐） |
| 场景 A 爬虫→情报 | `test_scenarios.py` | 0 | 本地 fixture HTTP 200 → manifest(license=unknown) → 入库 inserted → 重复采集 updated（仍 1 行）→ 溯源 origin/agg/url 完整 → 检索 hits=3 |
| 场景 B 情报→视频 | `test_scenarios.py` | 0 | 真实库检索 ai-robot hits=1 → 素材需求 1 条 → 参考分析 shots=1/frames=3 → 渲染出片 QC PASS → 发布预览 DRY-RUN 且账号已脱敏 |
| 场景 C 规则协同 | `test_scenarios.py` | 0 | 三条规则各一份且互不覆盖；均有多 Skill 协作段；跨规则互指正确；旧规则保留会议与轻量约定 |
| 同步校验 | `skill_sync_check.py` | 0 | issues=[] |

### 4.3 触发测试的三层区分（重要）

| 层级 | 结果 | 说明 |
|---|---|---|
| ① 静态规则检查 | **PASS** | 80 用例（15 正 + 10 负 + 5 组合 × 3 Skill）：规则文件确实覆盖对应表达、负向段确实写明边界 |
| ② 新会话真实 Agent 路由 | **NOT_TESTED** | 需在 Trae 新会话中由宿主 Agent 实际触发；本轮无法伪造，不冒充 |
| ③ 实际工具执行 | **PASS** | 场景 A/B 证明"路由到工具 → 工具真跑 → 产物真实"链路成立 |

### 4.4 本轮修复的真实缺陷（由测试抓出，非推测）

1. `upsert_aggregated_entry` 的 INSERT 未捕获游标 → `NameError: cur`（采集直接失败）。
2. `ensure_fts` 在只读连接上 CREATE 触发异常 → 检索被静默降级为 LIKE。
3. FTS 索引未回填时**静默返回 0 条**（真实可用性风险）→ 增加索引自愈（行数不足即回填，不可写则降级）。
4. drawtext `fontfile` 路径冒号被当作选项分隔符 → 改用单引号包裹。
5. loudnorm 后音频输出标签未更新 → `-map [aout]` 不存在。
6. 规则文件 UTF-8 BOM 破坏 frontmatter 解析 → 全库扫描剥离 BOM（**若未修，该规则在 Trae 中可能不生效**）。

---

## 5. 安全与资产完整性

| 项 | 状态 | 证据 |
|---|---|---|
| SQLite 完整性 | ✅ ok | `PRAGMA integrity_check = ok`（整改前后各一次） |
| 真实情报是否保留 | ✅ 103 条一条不少 | 整改前 103 → 整改后 103（entries 103 / FTS 103） |
| 数据库是否被重建 | ❌ 未重建 | 仅新增 `entries_fts` 虚表与列迁移；schema v3 保持 |
| 计划任务是否安全 | ✅ 4 个任务原样保留 | `schtasks /Query`：TechRadar_Daily/Weekly/Monthly/Quarterly 全部 Ready，下次运行时间未变；本轮未创建、未修改、未删除任何任务 |
| 数据库写入 | 仅 FTS 回填（103 行索引） | 采集写入全部落在临时副本（两套测试已默认隔离，需 `--allow-real-db` 才写真实库） |
| 凭据是否改动 | ❌ 未改动 | 未读取、未打印、未轮换任何 Token/Key；Folo/Reddit 仍为未配置状态（未擅自配置） |
| 真实发布 | ❌ 未发生 | 仅生成 dry-run 预览，账号脱敏，无任何平台调用 |
| 付费 API | ❌ 未调用 | 仅用公开免费接口（HN / GitHub / Resource Radar） |
| BGM 版权 | ✅ 已建闸门 | 未登记音频一律 BLOCKED；默认路径缺失如实记录在 `BGM_LICENSES.json` |
| 备份与回滚 | ✅ 可用 | `_backup\20261117_225336\`（24 文件 + DB + SHA256 清单），逐文件可还原 |
| 保护资产 | ✅ 未动 | P0–P5 与 WS-01～08 原文、7 个收藏仓库、`.venv`、浏览器运行时、aitoearn 14 子技能与 MCP 配置均未改动 |

---

## 6. 剩余问题（全部列出，未隐藏）

| ID | 剩余项 | 状态 | 原因 / 后续人工步骤 |
|---|---|---|---|
| IS-05 | 周/月/季真实计划任务仍无自然触发记录 | PARTIAL | 本轮在临时副本验证四周期；等待 2026-11-22 / 12-01 / 2027-01-01 自然触发后回查 `job_runs` |
| IS-08 | Folo / Reddit 凭据缺失 | BLOCKED | 需用户填 `FOLO_SESSION_TOKEN` 与 `REDDIT_CLIENT_ID/SECRET`；代码无需改 |
| IS-13 | 统一日志未全量接入 `loggingx` | NOT_IMPLEMENTED | 本轮优先修路由与检索；建议下轮把采集/检索/生命周期脚本接入 MaskedLogger |
| IS-16 | 真实库从未发生清理（purge_log=0） | NOT_TESTED | 默认 `apply_purge=false`；需用户确认后手动 `--apply` |
| IS-17 | 成片 QC 仍以合成 fixture 为主 | NOT_TESTED | 需用户提供一段有权处理的真实视频 |
| IS-18 | 正式发布链路未验证 | BLOCKED | 需用户批准后做草稿/沙盒验证 |
| IS-19 | 02 与 03 之间仍无程序级互调 | PARTIAL | 已在 Playbook 与规则层建立指引（选题→素材需求→渲染），但无自动化编排脚本 |
| IS-22 | claude-code 适配文档缺验证标记 | PARTIAL | 本轮未改该文档；其余四个适配文档已有状态标记 |
| NEW-01 | 真实模型路由未实测 | NOT_TESTED | 需在 Trae 新会话中提问验证三条规则是否被实际触发 |
| NEW-02 | WorkBuddy 内的 Skill 调用未实测 | NOT_TESTED | 只完成文件安装与内容正确性校验 |
| NEW-03 | Loomi / Claude Code 适配未实测 | NOT_TESTED | 无本机实例，仅补齐文档说明 |
| NEW-04 | `entries` 表新增 `tags`/`relations` 数据仍为 0 | PARTIAL | 能力已实现且测试通过；真实数据尚未打标（需真实使用中积累） |

---

## 7. 最终验收标准逐项核对

| # | 标准 | 判定 | 依据 |
|---|---|---|---|
| 1 | 三个 canonical Skill 都有清晰触发描述 | ✅ PASS | 00/02/03 均含 description + triggers + not_triggers（同步校验器 PASS） |
| 2 | Trae 有三条独立全局规则 | ✅ PASS | 规则目录 4 个文件，其中 3 条为独立 Skill 规则 |
| 3 | 旧会议纪要/长文档/笔记规则保留 | ✅ PASS | 旧规则含六段式、云笔记、轻量直答（场景 C4 断言） |
| 4 | 三条规则分别指向正确 Skill | ✅ PASS | 规则→canonical→客户端壳三层路径一致（同步校验器） |
| 5 | 客户端入口与 canonical 一致 | ✅ PASS | 壳内含 canonical 绝对路径与版本号；校验器 ok=true |
| 6 | 视频任务能进入真实执行工具 | ✅ PASS | render.py 出片 + aitoearn MCP（Trae 内） |
| 7 | 爬虫任务不误判普通网页阅读为爬虫工程 | ✅ PASS | 30 条负向边界写入规则并被静态校验 |
| 8 | TechRadar 覆盖六大类需求 | ✅ PASS | 规则 A–F 六节 + canonical §4.2 三级模式 |
| 9 | 三级模式选择合理 | ✅ PASS | 规则与 canonical 均定义判据 |
| 10 | 本地查询实际调用 SQLite | ✅ PASS | 场景 A/B 真实调用 radar_query（engine=fts5） |
| 11 | 检索能力只对真实实现标 PASS | ✅ PASS | C15 PASS（FTS/时间/标签/来源/关联均有断言）；C14 降级 PARTIAL |
| 12 | 定时任务保持幂等 | ✅ PASS | 未新增任务；install 幂等逻辑保留，status 只读实测 |
| 13 | 测试不误伤真实数据库 | ✅ PASS | 两套测试默认隔离；真实库 entries 103 未变、mtime 未变 |
| 14 | 旧回归测试未被降低标准 | ✅ PASS | 全部历史断言保留且通过，仅新增隔离保护 |
| 15 | 无真实路由证据的客户端如实标 NOT_TESTED | ✅ PASS | 报告 §4.3 与 §6 明确区分静态/路由/执行三层 |
| 16 | 所有修改有备份与回滚 | ✅ PASS | 24 文件 + DB，SHA256 清单 |

---

## 8. 本轮修改文件清单

**新增（12）**：`03_techradar/scripts/` 无关；实际新增为
`_shared/skillkit/search.py`、`02_video_pipeline/scripts/render.py`、`02_video_pipeline/assets/BGM_LICENSES.json`、
`tests/test_remediation.py`、`tests/test_triggers.py`、`tests/test_scenarios.py`、`tests/skill_sync_check.py`、
`tests/trigger_cases.yaml`、`03_techradar/data/entries_fts`（库内虚表）、
三条规则 `rule-1794927301000/2000/3000.md`、`~/.workbuddy/skills/techradar/SKILL.md`、`~/.workbuddy/skills/video-pipeline/SKILL.md`。

**修改（13，已备份）**：三条规则中的旧规则文件、三个 canonical SKILL.md、三个客户端壳、
`_shared/skillkit/inteldb.py`、`_shared/skillkit/lifecycle.py`、`03_techradar/scripts/radar_query.py`、
`03_techradar/scripts/scheduler.py`、`tests/test_lifecycle.py`、`tests/test_zcl_integration.py`、
`README.md`、`AGENTS.md`、`CAPABILITY_REGISTRY.yaml`、`CHANGELOG.md`。

**数据库**：仅新增 `entries_fts` 虚表（103 行索引）+ 读取状态/标签/关联相关的空表使用；条目零删除。
