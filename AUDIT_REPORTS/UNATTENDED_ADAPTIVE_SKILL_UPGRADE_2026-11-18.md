# UNATTENDED_ADAPTIVE_SKILL_UPGRADE_2026-11-18.md — 无人值守自适应升级报告

- 执行窗口：2026-11-18 00:49 – 02:05
- 范围：爬虫 Skill 能力升级 + 视频真实混剪 + 情报补采 + 工具层集成
- 原则：不伪造、不绕验证码/登录/付费墙、不导出凭据、不真实发布

---

## 1. 阶段状态总表

| 阶段 | 内容 | 状态 | 关键证据 |
|---|---|---|---|
| P0 资产审计与备份 | 备份 DB + 7 文件，记录 SHA256 | **PASS** | `_backup/20261118_004930/manifest.csv` |
| P1 情报驱动调研 | 本地检索 + 主题补采 43 条 | **PASS** | 库 346→389；`reports/INTELLIGENCE_DRIVEN_TECH_REQUIREMENTS.md` |
| P2 基线兼容性 | 8 目标公开探测 + 3 平台登录态判定 | **PASS（含 PARTIAL/BLOCKED 如实标注）** | `reports/platform_matrix.md` |
| P3 项目真实性审计 | 8 候选 + MagicalMirror 搜索 | **PASS** | `_reports/probes/github_candidates.json` |
| P4 隔离环境实测 | trafilatura 2.3.1 + readability | **PASS** | `_reports/probes/extract_bench.json` |
| P5 集成与文档 | 4 个工具 + SKILL §8 + 4 份报告 | **PASS** | `00_crawl_Skills/scripts/*`、`SKILL.md` §8 |
| P6 视频真实混剪 | 55.54s 成片 + QC + 封面 + 预览 | **PASS（BGM 身份 PARTIAL）** | `E:\Trae_Video_Workspace\outputs\v4_montage_20261118.mp4` |
| P7 规则一致性 | 4 条规则存在、无新增冲突 | **PASS** | 规则目录 4 文件 |
| P8 第一轮自检 | 12 套测试 + 数据完整性 | **PASS** | 见 §6 |
| P9 重启验证 | **无法重启 Trae 客户端** | **BLOCKED（已用冷启动等价验证替代）** | 见 §7 |
| P10 交付报告 | 本文件 | **PASS** | — |

---

## 2. Phase 1：情报驱动的能力需求（真实数据）

- 本地库检索"scrap/crawl/playwright/trafilatura/firecrawl/crawlee"：**0 命中**（不是猜测，是 SQL 计数）。
- 用新增 `collect_topic.py` 从 HN + GitHub 补采三个主题：抓取 48、新增 **43**、去重 5。
- 库内条目 346 → **389**，全部带原始链接与发布时间。
- 由此映射出的能力需求、优先级与 ROI 见 `reports/INTELLIGENCE_DRIVEN_TECH_REQUIREMENTS.md`。

## 3. Phase 2：基线兼容性（实测结论）

| 平台 | 结果 |
|---|---|
| Bilibili | **OK**：公开 API `x/web-interface/popular` 返回 `code=0`，可直接采集 |
| Douyin | **PARTIAL/BLOCKED**：页面 200，但热榜接口返回非 JSON（需签名）；登录态触发风控 |
| 小红书 | **PARTIAL**：SPA 空壳 + `__INITIAL_STATE__`；登录态触发风控 |
| YouTube | **OK**：SSR 页面可读；播放地址解析 NOT_TESTED |
| 通用文章站 | **OK**：SSR + JSON-LD，抽取链路可用 |
| Reddit | **BLOCKED**：403，必须 OAuth |

**登录态使用说明（按用户授权）**：仅复用本机 `browser_profile`，只做页面可见状态判定；
未读取/导出任何 Cookie、localStorage 或密码；抖音/小红书检测到验证/风控即停止，**0 次绕过尝试**。
当前 profile 判定为未登录/被拦截，因此"登录态深度采集"标记 **BLOCKED**，需用户手动登录后重试。

## 4. Phase 3/4：技术采纳（依据真实审计）

- 8 个候选全部 API 核实：stars、最近推送、归档状态、许可证（见 `reports/TECH_ADOPTION_REPORT.md`）。
- **MagicalMirror 实测仅 1 star、2020 年停更 → 拒绝**，不因网传热度引入。
- 隔离 venv 实测：trafilatura 在三站点均最干净；readability 在 github.blog 失效（238 字符）；
  内置兜底始终可用但噪音大。**采纳 trafilatura 为可选依赖，其余暂缓**。

## 5. Phase 5：集成

新增 4 个可执行工具（均在 `00_crawl_Skills/scripts/`）：

| 工具 | 作用 |
|---|---|
| `probe_site.py` | 公开探测：状态/渲染层/结构化数据/媒体线索/阻断词 |
| `probe_logged_in.py` | 授权登录态判定（不导出凭据、遇验证即停） |
| `extract_article.py` | 正文抽取三引擎降级 |
| `build_platform_matrix.py` | 兼容矩阵汇总（JSON + MD） |

`00_crawl_Skills/SKILL.md` 新增 §8（工具层、平台基线、登录态硬边界、采纳结论、抽取消歧）。
`03_techradar` 新增 `collect_topic.py`（主题检索补采），并写入 `topic_search` 来源状态。

## 6. Phase 6：视频真实混剪（指定任务）

### 6.1 成片

| 项 | 值 |
|---|---|
| 输出 | `E:\Trae_Video_Workspace\outputs\v4_montage_20261118.mp4` |
| 时长 | **55.54s**（要求 55–65s） |
| 画幅 | 1080×1080 / 30fps / H.264 / AAC 48k 立体声 |
| 大小 | 12,748,768 B |
| 响度 | -15.5 LUFS / True Peak -3.7 dBTP / LRA 7.2 |
| 黑帧 | 仅片尾淡出 0.43s，无中途黑屏 |
| 封面 | `outputs/v4_cover.jpg`（1080×1080，含"世界是一片荒原"） |
| 发布预览 | `work/v4_edit/publish_preview.md`（DRY-RUN，账号脱敏） |

### 6.2 时间线（EDL：`work/v4_edit/edl.json`）

| 段 | 来源 | 入点/时长 | 内容 |
|---|---|---|---|
| S1 | ref_02 | 0.00 / 11.52s | **开头保留"世界是一片荒原"** 与后续独白 |
| B1 | Coverr 雾丘 | 2.0 / 4.0s | 荒原感空镜（静音，BGM 抬升） |
| S2 | ref_02 | 11.52 / 9.24s | "以为换了的地方会好…新的地方痛苦" |
| B2 | Coverr 空城街道 | 3.0 / 3.0s | "换地方"的视觉注脚 |
| S3 | ref_02 | 33.77 / 7.28s | "你又能怎么办…看看周围" |
| B3 | Coverr 雾山 | 4.0 / 5.0s（实际 3.0s） | 情绪留白 |
| S4 | ref_02 | 41.05 / 17.45s | "所有人就换车…太噁心了"（避开片尾账号卡） |

### 6.3 音频

- **原声完整保留**：S1–S4 均使用源片同段音轨，声画同步。
- BGM：`bgm.mp3` 以 -14dB 进入，经 `sidechaincompress` 对白闪避；空镜段实测均值约 -34dB，
  对白段 -18.3dB → 对白清晰、BGM 可闻。
- **诚实标记**：`bgm.mp3` 无 ID3 标题，**无法确认是否为《志铭》**，故 `verified_identity=false`，
  该子项为 **PARTIAL**；换入正确的《志铭》文件即可复用同一 EDL 重渲。

### 6.4 补充素材与许可

| 文件 | 来源 | 许可 |
|---|---|---|
| foggy_hill.mp4 | Coverr `walking-on-a-foggy-hill-6616` | Coverr License（免费使用） |
| empty_road.mp4 | Coverr `view-of-empty-roads-in-buenos-aires-1479` | Coverr License |
| misty_mountains.mp4 | Coverr `misty-mountains-819` | Coverr License |

补充素材落地并 ffprobe 校验；未使用来源不明素材。

### 6.5 人工目检限制

成片缩略图因包含影视暴力镜头被图像合规检查拒绝展示，**无法完成逐帧目检**。
已改用可核验指标替代：黑帧检测、响度、分段电平、场景拼接点、EDL 时间线核对。
该限制如实记录，不声称"已目检通过"。

## 7. Phase 7–9：重启与自检

- **无法重启 Trae 客户端**（Agent 不能控制宿主 IDE 进程）。未执行任何重启命令。
- 替代验证：以**独立新进程**冷启动执行全部工具与测试（每个命令都是新 Python 进程，
  不依赖会话内状态），验证"重启后仍可用"的核心诉求；结果见 §8。
- 规则一致性：4 条规则文件存在（视频/爬虫/情报/会议），本轮未新增规则，无冲突。

## 8. 测试与回归

| 套件 | 退出码 | 说明 |
|---|---|---|
| `tests/test_crawl_tools.py`（新） | 0 | 18 项：分类/抽取/矩阵/探测/渲染/编码/凭据 |
| `tests/test_quality_review.py` | 0 | R1–R12 |
| `tests/test_dual_channel.py` | 0 | A/B/C/D |
| `tests/test_scenarios.py` | 0 | A/B/C |
| `tests/test_triggers.py` | 0 | 80 用例静态检查 |
| `tests/test_remediation.py` | 0 | 22 项 |
| `tests/test_lifecycle.py` | 0 | 四周期/保护/恢复 |
| `tests/test_zcl_integration.py` | 0 | 13 PASS |
| `tests/test_video_pipeline.py` | 0 | QC 好/坏片判定 |
| `tests/test_techradar.py` | 0 | 库结构/去重/状态机 |
| `tests/test_registry.py` | 0 | 18 项能力 |
| `tests/test_skillkit_contract.py` | 0 | 契约 |

数据库：389 条 / FTS 389 / `integrity_check=ok`；计划任务 4 个未改动；未真实发布。

## 9. 本轮修复的真实缺陷（第二轮自愈）

1. `montage_edit.py` 调色参数 `ms` 不存在 → 改为 `bm`，重渲成功。
2. `probe_site` 把 Wikipedia 正文里的 "verifiability" 误判为验证码 → 阻断词限定在标题+前 6000 字符，并收紧词表。
3. 兼容矩阵把"HTTP 200 但非 JSON"的抖音接口判为 OK → 改为 `BLOCKED(non_json)`。
4. 质量测试把 346 写死为快照 → 主题补采后库增至 389 导致误报；改为相对校验（≥346 且分组求和一致），
   并修正 registry 计数口径（已含 topic_search）。

## 10. 仍需人工处理

| # | 事项 | 状态 |
|---|---|---|
| 1 | 确认/替换《志铭》BGM 文件 | PARTIAL（当前 bgm.mp3 身份未证实） |
| 2 | 平台登录态 | BLOCKED（需在浏览器手动登录后重试） |
| 3 | 抖音/小红书深度采集 | BLOCKED（签名/风控，不绕过） |
| 4 | Reddit 审批与 Folo 令牌 | 仍 BLOCKED（沿用上一轮结论） |
| 5 | 成片逐帧目检 | BLOCKED（工具合规限制），已用技术指标替代 |
| 6 | 真实发布 | 未执行（按协议禁止） |
