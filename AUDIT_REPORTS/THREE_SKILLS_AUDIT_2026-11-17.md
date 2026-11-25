# 三个核心 Skill 全面审计与诊断报告

- 审计日期：2026-11-17
- 审计模式：**只读**（未修改、未删除、未安装、未创建/修改计划任务、未发布、未调用付费 API）
- 审计对象：`00_crawl_Skills`、`02_video_pipeline`、`03_techradar`
- 审计方法：真实文件读取 + 静态调用关系分析 + SQLite 只读查询（`mode=ro`）+ `schtasks /Query` 只读 + 单次公开 `GET /health` + 4 套隔离测试
- 判定口径：`PASS` 有真实执行证据；`PARTIAL` 部分实现/部分验证；`BLOCKED` 被凭据或环境阻塞；`FAIL` 实测失败；`NOT_TESTED` 本轮未执行；`NOT_IMPLEMENTED` 无实现
- 重要声明：本轮**没有**做真实 Agent 路由测试（无法在只读审计中伪造一次新会话），凡涉及"用户说一句话模型会不会触发"的结论，均标注为**规则静态分析**，不冒充实测

---

## 1. 审计范围与真实路径

### 1.1 实际检查路径（磁盘实测，非旧报告推断）

| 对象 | 实际路径 | 状态 |
|---|---|---|
| 库根 | `D:\00_skiill_ku` | 存在 |
| 爬虫 Skill | `D:\00_skiill_ku\00_crawl_Skills` | 存在（README 11,341 B + SKILL 11,545 B + 8 篇文档 + 7 个 git 仓库） |
| 视频 Skill | `D:\00_skiill_ku\02_video_pipeline` | 存在（SKILL 5,772 B + 4 个脚本） |
| 情报 Skill | `D:\00_skiill_ku\03_techradar` | 存在（SKILL 15,057 B + 7 个脚本 + 4 个 cmd + DB 307,200 B） |
| 共享底座 | `D:\00_skiill_ku\_shared\skillkit` | 存在（hashing / manifest / policy / loggingx / media / inteldb / canonical / lifecycle） |
| 测试 | `D:\00_skiill_ku\tests` | 6 个测试文件 |
| Trae 技能目录 | `C:\Users\26808\.trae-cn\skills` | 仅 `aitoearn`(55 文件)、`material-sourcing-crawler`(2)、`tech-radar`(1) |
| WorkBuddy 技能目录 | `C:\Users\26808\.workbuddy\skills` | 含 `web-scraping-playbook`，与库内 SKILL.md **SHA256 一致** |
| 全局规则 | `C:\Users\26808\.trae-cn\user_rules\rule-1794846677938.md` | 存在（alwaysApply） |
| 当前工作区 | `C:\Users\26808\Documents\Trae-CN\temp_20261117_03` | **无 AGENTS.md、无 .trae/rules** |

### 1.2 目录结构核实结论

- 三个目录名称与任务描述一致，无需改名。
- `00_crawl_Skills` 内**没有** `scripts/` 或可执行采集器，只有协议文档与 7 个收藏仓库。
- `00_crawl_Skills\Camoufox\`、`Playwright\` 目录**不存在**；实际运行时在 `D:\00_toolbox\00_crawl_Skills\{Playwright,Camoufox}`（均已确认存在）。
- `02_video_pipeline` 只有 4 个脚本，**没有**渲染/剪辑/字幕/配音/BGM 脚本。
- `03_techradar` 有完整采集、检索、生命周期、调度脚本与 SQLite 库。

---

## 2. 当前技能库总体架构

```
D:\00_skiill_ku
├── AGENTS.md                    # 给模型的跨客户端重建手册（不在工作区根，Trae 不自动加载）
├── CAPABILITY_REGISTRY.yaml     # 14 项能力注册表
├── README.md / INSTALLATION_GUIDE.md / VERIFICATION_RULES.md / CHANGELOG.md
├── 00_crawl_Skills/             # 协议库：P0–P5 + WS-01~08 + 7 repos（无自有 runner）
├── 02_video_pipeline/           # canonical 视频技能：素材验证/参考分析/QC/发布预览（无剪辑实现）
├── 03_techradar/                # 工程版情报系统：DB + 采集 + 检索 + 生命周期 + 调度
├── _shared/skillkit/            # 共享底座（被 02/03 引用）
├── adapters/                    # 5 个客户端适配说明
├── tests/                       # 6 套测试（2 套非隔离）
├── _backup/ _logs/ _reports/    # 备份、日志、报告
└── .venv/                       # 项目级 Python 环境（仅装 PyYAML）

客户端实际安装层（真正会被自动触发的）
├── ~/.trae-cn/skills/tech-radar/SKILL.md          # 会话版，10,059 B，不含 DB/脚本引用
├── ~/.trae-cn/skills/aitoearn/SKILL.md            # 视频执行版（14 子技能 + MCP）
├── ~/.trae-cn/skills/material-sourcing-crawler/   # 素材采集（2 文件）
└── ~/.workbuddy/skills/web-scraping-playbook/     # 爬虫协议副本（与库内一致）
```

**架构本质**：`D:\00_skiill_ku` 是"库/源头"，`~/.trae-cn/skills` 是"安装壳"。目前**只有 3 个壳**，且 `tech-radar` 壳与库内 `03_techradar` 内容不同源。这构成本轮最严重的结构性问题。

---

## 3. 三个 Skill 功能实现情况

### 3.1 A. 爬虫 Skill（`00_crawl_Skills`）

| 能力 | 实现位置 | 证据 | 状态 |
|---|---|---|---|
| 目标类型识别（DOM/XHR/API/SPA） | `SKILL.md` P0 四连命令 + 画像卡 | SKILL.md L45–83 | PASS（协议层面，有可执行命令） |
| 反爬分层定性 | `01_anti_scraping_sop.md` + `05_failure_taxonomy.md`（33 条症状） | 文档 6,047 B / 18,849 B | PASS（文档完整，未在本轮执行） |
| 技术选型（Playwright/Camoufox/patchright） | `01`、`02` | `02` L182 限速建议 | PASS（文档） |
| 合规约束（robots/服务条款/频率） | `SKILL.md` C9、`07` 第九节、`02` L183 | 实测命中 4 处 | PASS（协议层面） |
| 静态/动态/API 区分 | `SKILL.md` §P0 + WS-08 | — | PASS（文档） |
| 失败恢复/限速/重试/断点/去重 | `_shared/skillkit/policy.py`、`manifest.py`；WS-08 | 代码存在，测试 PASS | PASS（代码层，被 02/03 复用） |
| 真实采集结果验证 | **无自有脚本**；验证动作靠模型或外部 `material_crawler.py` | 目录内无 .py（repos 除外） | PARTIAL / NOT_IMPLEMENTED（库自身） |
| 复用浏览器运行时 | 环境变量 `PLAYWRIGHT_BROWSERS_PATH=D:\00_toolbox\...` | 两目录均存在（705.6 MB / 2,444.4 MB） | PASS（运行时在，路径已漂移出库） |
| 文档与代码一致性 | README 已修正运行时路径；AGENTS.md 仍写旧路径 | AGENTS.md L121 | PARTIAL |
| 跨客户端发现 | WorkBuddy 已装副本且哈希一致；Trae 未装 | 哈希 `53ABBEC0…` 相同 | PASS（WorkBuddy）/ PARTIAL（Trae） |

**结论**：作为"方法论 + 契约库"质量高；作为"可执行采集能力"缺自有 runner，且 frontmatter **没有 `description` 字段**，自动触发依赖客户端对 `name` 的匹配。

### 3.2 B. 视频处理与发布 Skill（`02_video_pipeline`）

| 能力 | 实现位置 | 证据 | 状态 |
|---|---|---|---|
| 素材发现 + 校验 + 清单 | `verify_asset.py`（5,144 B） | 限速/退避/MIME/PIL/ffprobe/SHA256/去重 | PASS（隔离测试） |
| 参考视频分析 | `reference_analyze.py`（3,686 B） | ffprobe + scene cut + 抽帧 + timeline/style | PASS（合成视频） |
| 剪辑 / 字幕 / 配音 / BGM / 转场 / 导出 | **无** | 4 个脚本中无 `drawtext/xfade/amix/loudnorm/libx264` | **NOT_IMPLEMENTED** |
| 质量门禁（黑屏/无声/画幅/时长） | `video_qc.py`（4,908 B） | 好片 PASS、坏片 FAIL 实测 | PASS（合成 fixture） |
| 真实成片 QC | 无记录 | `_reports` 无 video_qc 产物 | NOT_TESTED |
| 测试视频与正式素材区分 | `license_status=unknown` 默认 | manifest 契约 | PARTIAL（有标记，无强制拦截） |
| 发布 dry-run / 人工确认 | `publish_preview.py`（2,930 B） | 无网络调用（grep 无 requests/http） | PASS |
| BGM 版权与来源 | 文档提示，但 `bgm.mp3` 缺失 | `Test-Path E:\...\bgm.mp3 = False` | BLOCKED |
| 客户端内可用性 | Trae 靠 `aitoearn`（已装）；非 Trae 无替代 | aitoearn SKILL 存在 | PARTIAL（生态绑定） |
| 失败恢复/日志/交付 | 脚本有返回码与 JSON 产物；无统一日志 | `loggingx` 未被调用 | PARTIAL |

**结论**：这是一个"素材 + 分析 + 质检 + 发布预览"的半成品流水线，**不是完整剪辑系统**。SKILL §0 写的"⑤ 生成/渲染（ffmpeg 主链路）"在脚本层没有任何实现，实际依赖模型临场写 ffmpeg 或 Trae 的 aitoearn。

### 3.3 C. TechRadar 技术情报 Skill（`03_techradar`）

| 能力 | 实现位置 | 证据 | 状态 |
|---|---|---|---|
| 接入并维护已配置来源 | `collect_public.py` / `collect_zcl.py` / `healthcheck.py` | 3 个 source 行；HN/GitHub/资源雷达 | PARTIAL（Folo/Reddit BLOCKED） |
| Resource Radar 接入 | `collect_zcl.py`（8,840 B） | 单次 GET `/health` → 200 `ok=true` `docker-readonly` | PASS |
| 区分原始源与聚合源 | `origin_source` / `aggregator` + 严格判定 | `_is_github` 修正 `r/*github*` 误判 | PASS |
| 跨源去重/溯源 | `canonical_key` + `external_key` | 6 个索引；跨源测试历史 PASS | PASS |
| 可靠入库 SQLite | `inteldb.py` | 103 条、schema v3、integrity 历史 PASS | PASS |
| 全文检索 | **无 FTS 表**；`radar_query.py` 用 `LIKE` | `FTS: NONE` | PARTIAL / NOT_IMPLEMENTED |
| 标签检索 | `tags` / `entry_tags` 均为 0 行，无写入逻辑 | 只读查询 | NOT_IMPLEMENTED |
| 时间检索 | `radar_query.py` 只按场景关键词，无时间窗参数 | L59–62、L90–96 | NOT_IMPLEMENTED |
| 关联检索 | `relations` 0 行，无查询入口 | 表存在无数据无 API | NOT_IMPLEMENTED |
| 按问题检索（非纯关键词） | 场景预设 3 组 + 项目画像权重 | 代码写死 `SCENARIOS` | PARTIAL |
| 有证据的技术分析 | SKILL §4.1 要求五要素核验；无自动校验 | 文档规范 | PARTIAL（靠模型自律） |
| 采集日志/健康检查/异常恢复 | `healthcheck.py` + `job_runs` + `reap_stale_runs` | 6 条 job_runs（含 1 条 FAIL） | PASS |
| 价值评分/生命周期/归档/备份/清理 | `lifecycle.py` + `lifecycle_run.py` | 14 条策略；36 项测试历史 PASS | PASS（副本验证） |
| 日/周/月/季流程 | `lifecycle_run.py` 四 job | 四类均有实现 | PASS（仅 daily 实跑） |
| 定时任务规则写入 Skill | SKILL §0 / §6 | 15,057 B | PASS |
| 幂等避免重复创建 | `config_hash` 比对 | 二次 install 全 EXISTS_OK（历史） | PASS |
| 客户端关闭后继续执行 | Windows 任务计划程序 | `schtasks` 4 任务，daily Last Result=0 | PASS（仅 daily 证明） |
| 换客户端接管既有任务 | `TASK_REGISTRY.json` + `task_registry` 表 | 4 行注册 | PASS（设计层） |
| 不支持后台时如实报告 | `scheduler.py:action_install` 非 Windows 分支 | 输出 canon 命令 | PASS（代码层） |

**结论**：三个 Skill 中工程完成度最高，但**它自己没有被安装进任何客户端**，真正被触发的 `tech-radar` 壳完全不知道这个库的存在（见 IS-01）。

---

## 4. 代码、配置、文档一致性

| 检查项 | 实际情况 | 判定 |
|---|---|---|
| 03 SKILL §3 标题 | 写 "Schema v2"，实际 `schema_meta=v3` | 不一致（P3） |
| README 能力数量 | 写 "12 项能力"，`CAPABILITY_REGISTRY.yaml` 实为 14 项 | 不一致（P3） |
| AGENTS.md 运行时路径 | L121 写 `D:\00_skiill_ku\00_crawl_Skills\Playwright`，实际 `D:\00_toolbox\...` | 不一致（P2） |
| 00_crawl README vs 目录 | 已注明内核迁移，篇数 WS-01~08，`00_index.md` count=8 | 一致 |
| 02 SKILL §0 vs 脚本 | 声称"ffmpeg 主链路渲染"，无渲染脚本 | 不一致（P1） |
| 03 SKILL §4.1 vs 检索脚本 | 要求时间/来源/热度核验，脚本无时间过滤 | 部分不一致 |
| lifecycle 配置 vs policy 表 | 14 条策略双向写入，无一致性校验 | 一致（无校验，P3） |
| 测试路径 vs 真实库 | 2 套测试写真实库 | 设计缺陷（P2） |
| 客户端壳 vs 库 | tech-radar 10,059 B vs 15,057 B；mtime 14:40 vs 22:27 | 漂移（P1） |

---

## 5. 全局规则与触发条件审计

### 5.1 实际触发链路（按加载优先级）

1. **全局规则** `rule-1794846677938.md`（`alwaysApply: true`）：
   只点名 `/tech-radar`，覆盖"技术选型 / 代码优化 / 架构设计 / 开源库调研 / 会议录音 / 长文档 / 云端笔记"。
   **完全没有提到** `00_crawl_Skills`、`02_video_pipeline`、`03_techradar`。
2. **客户端技能描述**（Trae 目录扫描）：只有 `tech-radar`、`aitoearn`、`material-sourcing-crawler` 三个描述可被匹配。
3. **AGENTS.md**：在库根，**当前工作区根没有**，Trae 不会自动加载；即使加载，它只是"重建手册"，不是路由规则。
4. **Skill 内部自述**：`02`/`03` 的 SKILL.md 有 description，但文件不在技能目录 → 不会被扫描。

### 5.2 六个必答问题

| 问题 | 结论 | 证据 |
|---|---|---|
| 用户说什么会触发爬虫 Skill？ | 实际只会触发 `material-sourcing-crawler`（"找素材/抓网页数据"）或 `tech-radar`（"技术选型"间接引用武器库）；`00_crawl_Skills` 本身**不会**被 Trae 自动触发 | 客户端目录只有 3 个技能；全局规则无爬虫条目 |
| 说什么会触发视频 Skill？ | "剪辑/加字幕/发布/找素材"→ `aitoearn`；`02_video_pipeline` **不会**触发 | 02 不在技能目录 |
| 说什么会触发 TechRadar？ | "技术选型/代码优化/架构设计/开源库调研/会议纪要/长文档/云笔记"→ 触发 | 全局规则 L6–10 |
| 哪些表达容易漏触发？ | "帮我盯一下这个领域的新项目""这个库还维护吗""上周有什么值得看的""帮我搭个知识库"——不含"技术选型"字样，规则不覆盖 | 规则仅列 7 类意图 |
| 哪些场景会错误触发？ | "帮我抓这个网页正文"可能被 `material-sourcing-crawler`（素材）与 `tech-radar`（重型爬虫）同时争抢；"分析这个视频"可能被 `tech-radar` 的 media 关键词误导 | 两个描述都含"爬虫/抓取" |
| 规则是否冲突？ | 是：`tech-radar` 描述含"本地重型爬虫武器库"，与 `material-sourcing-crawler` 的"自动联动爬虫武器库"重叠；`aitoearn` 的描述含"剪辑/发布"，与 `02` 的 canonical 定位重叠 | 见 IS-11 |
| 是否存在"Skill 在但不知道何时用"？ | **存在且严重**：`02_video_pipeline`、`03_techradar`、`00_crawl_Skills` 三个目录都不在客户端发现路径 | 见 IS-02 |
| 是否存在"规则有触发条件但 Skill 无流程"？ | 是：全局规则要求 `/tech-radar`，但触发态 SKILL 没有本地库/脚本流程 | IS-01 |
| 是否存在"Skill 要能力但客户端无工具"？ | 是：`03` 的 §0 要求跑 `scheduler.py`，但该 Skill 不在技能目录，模型不会主动去 `D:\...` 执行；`02` 要求 ffmpeg 渲染但无脚本 | IS-01 / IS-03 |

---

## 6. 正向与负向触发矩阵

> 说明：`实测结果` 列中 **"规则命中"= 静态分析确认描述/规则含对应语义**；**"竞争"= 多个技能同时命中**；**"未命中"= 无任何规则覆盖**；**"NOT_TESTED"= 需要真实模型路由，本轮只读不伪造**。

### 6.1 爬虫 Skill

| # | 用户意图 | 应触发 | 触发关键词/语义 | 不应触发的相似场景 | 当前规则位置 | 实测结果 |
|---|---|---|---|---|---|---|
| 1 | 抓某个网站的数据 | crawl | 抓取/爬/采集 | 只要文章摘要 | material-sourcing 描述、tech-radar P0 | 竞争（两个技能） |
| 2 | 页面 403 怎么破 | crawl | 403/被拦 | 网站打不开（网络故障） | tech-radar P0 §4 | 规则命中（间接） |
| 3 | 下载 B 站视频失败 | crawl | B站/下载失败 | 视频剪辑 | tech-radar P0 | 规则命中（间接） |
| 4 | 写 Playwright 翻页脚本 | crawl | Playwright/翻页 | 前端自动化测试 | WS-06 | 未命中（无路由规则） |
| 5 | 接口有 sign 参数 | crawl | sign/加密参数 | 普通 API 调用 | WS-07 | 未命中 |
| 6 | 多站点聚合每天跑 | crawl | 聚合/定时 | 单页抓取 | WS-04 | 未命中 |
| 7 | 登录态抓取 | crawl | 登录态/cookie | 登录功能开发 | WS-03 | 未命中 |
| 8 | 采集去重断点 | crawl | 去重/断点 | 数据库唯一索引 | WS-08 | 未命中 |
| 9 | 抓小红书/知乎 | crawl | 小红书/知乎 | 内容分析 | material-sourcing | 规则命中 |
| 10 | 反爬怎么定位 | crawl | 反爬/空壳 | 性能优化 | WS-01/02 | 未命中 |
| N1 | 总结这篇文章 | 不应 crawl | — | 抓正文 | — | 可能误触发 material-sourcing |
| N2 | 推荐几个爬虫库 | TechRadar | 技术选型 | 直接抓取 | 全局规则 | 规则命中 |
| N3 | 剪个视频 | video | — | 下载视频 | — | 未命中（正确） |
| N4 | 查 MySQL 慢查询 | 直接答 | — | 网页抓取 | 全局规则 C 模式 | 未命中（正确） |
| N5 | 录音转纪要 | TechRadar B | — | 抓字幕 | 全局规则 | 规则命中 |

### 6.2 视频 Skill

| # | 用户意图 | 应触发 | 触发关键词/语义 | 不应触发的相似场景 | 当前规则位置 | 实测结果 |
|---|---|---|---|---|---|---|
| 1 | 把素材剪成短视频 | video | 剪辑/短视频 | 下载视频 | aitoearn 描述 | aitoearn 命中；02 未命中 |
| 2 | 加字幕 | video | 字幕/ASR | 翻译字幕文本 | aitoearn | 规则命中 |
| 3 | 分析爆款视频节奏 | video | 参考分析/节奏 | 视频转录 | 02 SKILL §2 | 02 不可达 |
| 4 | 检查成片黑屏无声 | video | 质检/黑屏 | 播放器问题 | 02 §4 | 02 不可达 |
| 5 | 做 9:16 竖屏 | video | 竖屏/裁切 | 图片裁剪 | aitoearn | 规则命中 |
| 6 | 配 BGM | video | BGM/配乐 | 音乐推荐 | aitoearn + 02 §6 | 规则命中但文件缺失 |
| 7 | 生成发布预览 | video | 发布/dry-run | 真实发布 | 02 §5 | 02 不可达 |
| 8 | 找城市夜景素材 | 素材 | 素材/找图 | 版权咨询 | material-sourcing | 规则命中 |
| 9 | 批量数据榜单视频 | video | 模板/批量 | 数据报表 | 02 §3（Remotion） | 未实现 |
| 10 | 剪映自动化加花字 | video | 花字/模板 | 手动剪辑教学 | 02 §3（降级通道） | NOT_IMPLEMENTED |
| N1 | 写个 Python 爬虫 | crawl | — | 视频脚本 | material-sourcing | 未命中（正确） |
| N2 | 分析 GitHub 视频模型 | TechRadar | — | 视频剪辑 | 全局规则 | 规则命中 |
| N3 | 帮我 P 图 | image-edit | — | 视频封面 | aitoearn | 规则命中（正确） |
| N4 | 写篇文章 | 写作 | — | 视频文案 | — | 未命中（正确） |
| N5 | 部署网站 | deployment | — | 视频发布 | — | 未命中（正确） |

### 6.3 TechRadar Skill

| # | 用户意图 | 应触发 | 触发关键词/语义 | 不应触发的相似场景 | 当前规则位置 | 实测结果 |
|---|---|---|---|---|---|---|
| 1 | 最近值得关注的 AI 开源项目 | TechRadar | 技术雷达/开源 | 单纯搜索一个库 | 全局规则 · 客户端 tech-radar | 规则命中（但不读库） |
| 2 | 帮我做技术选型 | TechRadar | 技术选型 | 代码报错 | 全局规则 L7 | 规则命中 |
| 3 | 做 AI Robot 有什么新组合 | 03 canonical | 具身/VLA | 硬件采购 | 03 §4.1 | 03 不可达 |
| 4 | 训练小模型用什么框架 | 03 canonical | 小模型/微调 | 模型推理报错 | 03 §4.1 | 03 不可达 |
| 5 | 抖音怎么合规涨粉 | 03 canonical | 内容增长 | 刷量代刷 | 03 §4.1 + 合规闸门 | 03 不可达 |
| 6 | 读我的 Folo/Reddit 订阅 | TechRadar | 订阅/情报源 | 直接搜索 | 客户端 A0 | 规则命中，凭据 BLOCKED |
| 7 | 把这段录音整理成纪要 | TechRadar B | 会议/长文档 | 语音转文字 | 全局规则 L8 | 规则命中 |
| 8 | 检查情报库和定时任务 | 03 canonical | 生命周期/调度 | 系统运维 | 03 §0 | 03 不可达 |
| 9 | 上周有哪些新项目 | 03 canonical | 时间检索 | 新闻摘要 | 03 §4（时间检索缺失） | 03 不可达 |
| 10 | 把这条情报入库 | 03 canonical | 入库/去重 | 收藏网页 | 03 §3 | 03 不可达 |
| N1 | 抓这个网页正文 | crawl | — | 情报采集 | tech-radar P0 | 竞争触发 |
| N2 | 剪视频 | video | — | 素材情报 | aitoearn | 未命中（正确） |
| N3 | 数据库报错 | 轻量解答 | — | 技术选型 | 全局规则 C | 规则命中（正确） |
| N4 | 翻译一段英文 | 直接答 | — | 情报分析 | — | 未命中（正确） |
| N5 | 部署上线 | deployment | — | 发布情报 | — | 未命中（正确） |

### 6.4 规则体系问题定位

| 问题类型 | 具体表现 | 位置 |
|---|---|---|
| 过于宽泛 | `tech-radar` 描述含"研发情报枢纽""重型爬虫"，覆盖了爬虫与情报两类意图 | 客户端 SKILL frontmatter |
| 过于严格 | 全局规则只列 7 类意图，"跟踪领域动态""这个库还维护吗"不在其中 | user_rules L6–10 |
| 多 Skill 竞争 | `tech-radar` vs `material-sourcing-crawler` 抢"抓网页"；`aitoearn` vs `02` 抢"剪辑" | 两个描述 |
| 全局与内部冲突 | 全局要求 `/tech-radar`，该壳不含本地库流程；canonical 03 要求启动自检，但不会被执行 | IS-01 |
| 提了 Skill 无入口 | AGENTS.md 提到 03/02，但不在发现路径；工作区没有 AGENTS.md | 1.1 表 |
| 要求能力无工具 | 03 §0 要求跑脚本，但模型无从知道库路径（除非用户明说） | 03 SKILL §0 |
| 更新不同步 | 03 v1.2.0（15 KB）vs 客户端 tech-radar（10 KB，无版本号） | 文件对比 |
| 新客户端无法理解 | `00_crawl_Skills` 无 `description`；`02/03` 虽有 description 但未安装 | frontmatter 实测 |

---

## 7. 三个 Skill 之间的协作关系

| 协作维度 | 现状 | 判定 |
|---|---|---|
| 爬虫采集内容进入 TechRadar | 共享 `_shared/skillkit`（policy/manifest），但 TechRadar 只用 `inteldb`，没有调用爬虫库 | PARTIAL（共用底座，无流程编排） |
| TechRadar 调用爬虫能力 | SKILL §2 S3 提到"爬虫库 Playwright"，脚本层无调用 | PARTIAL（文档层） |
| 视频 Skill 使用 TechRadar 素材/技术参考 | 完全无引用（grep 无 `03_techradar`） | NOT_IMPLEMENTED |
| 重复实现 | `02/verify_asset.py` 与客户端 `material_crawler.py` 都能下载素材；`collect_public` 与 `collect_zcl` 各自实现采集 | PARTIAL（有重复） |
| 统一日志 | `loggingx.py` 存在，但 02/03 所有脚本**均未调用** | NOT_IMPLEMENTED |
| 统一错误处理 | 各脚本自定义返回码/JSON，无统一错误模型 | PARTIAL |
| 统一配置 | 只有 `lifecycle_config.json`；02 无配置；路径硬编码在脚本 | PARTIAL |
| 统一能力注册 | `CAPABILITY_REGISTRY.yaml` 14 项，覆盖三者 | PASS（文档层） |
| 路径/依赖/数据库冲突 | 共用 `_shared` 与 `.venv`，无冲突；但 `sys.path` 用 `parents[2]` 相对定位，移动目录即断 | PASS / 脆弱 |
| 多客户端共享本地能力 | 脚本是纯文件，可复制；但客户端壳未安装 02/03 | PARTIAL |

**是否应抽取公共能力**：`skillkit` 已经承担了哈希/清单/策略/媒体/DB，方向正确，**不建议再抽象**（会过度设计）。真正缺的是"编排层"（谁调用谁），不是"更多公共库"。

---

## 8. 客户端兼容性审计

| 客户端 | 爬虫 | 视频 | 情报 | 证据 |
|---|---|---|---|---|
| Trae | PARTIAL（`material-sourcing-crawler` 装；`00_crawl_Skills` 未装） | PASS（`aitoearn` 装）/ 02 未装 | PARTIAL（`tech-radar` 装但不含 DB） | 目录实测 |
| WorkBuddy | PASS（`web-scraping-playbook` 哈希一致） | NOT_TESTED（无视频技能） | NOT_TESTED | 目录实测 |
| Loomi | NOT_TESTED（适配文档自述"待实测"） | NOT_TESTED | NOT_TESTED | adapters/loomi |
| Claude Code | NOT_TESTED（文档给了 `claude mcp add`，本机无 CLI 实例） | NOT_TESTED | NOT_TESTED | adapters/claude-code |
| 通用 Agent | 脚本可跑（纯 Python） | 脚本可跑（需 ffmpeg） | 脚本可跑（需 Python） | 代码层 |

平台耦合点（会阻碍跨客户端）：

- `scheduler.py` 使用 `schtasks` + `mbcs` 编码 + `.cmd` 包装 → 仅 Windows；非 Windows 分支会输出 BLOCKED + cron 示例（设计正确）。
- 所有脚本用 `Path(__file__).parents[2]` 定位 `_shared` → 目录层级不能变。
- `03` 的任务路径硬编码 `D:\00_skiill_ku\...` 于 `.cmd` 内，换机需重新 install。

---

## 9. 安全性、权限与外部副作用风险

| 风险项 | 现状 | 判定 |
|---|---|---|
| 密钥泄漏 | 库内扫描 `cn_*/sk-*/iv1*` 仅 1 处命中，位于 `tests/test_skillkit_contract.py:63`，是脱敏测试的**假 token** | PASS（无真实密钥） |
| 凭据存在性 | `FOLO_SESSION_TOKEN` 未设置；`REDDIT_CLIENT_ID/SECRET` 未设置；`aitoearn X-Api-Key` 已设置（未打印） | BLOCKED（2）/ 存在（1） |
| 真实发布 | `publish_preview.py` 无网络调用；文档禁止自动发布 | PASS |
| 删除数据 | 默认 `apply_purge=false`；`--apply` 也被二次拦截；删除前备份 + purge_log | PASS（设计）/ 未真实演练 |
| 计划任务副作用 | 4 个任务已存在；本轮只 `schtasks /Query`，未修改 | PASS |
| 素材版权 | `license_status` 默认 `unknown`，无自动授权核验 | PARTIAL（有标记无强制） |
| BGM 版权 | `bgm.mp3` 缺失，也无授权登记文件 | BLOCKED |
| 隐私 | `_backup` 内含数据库副本（103 条公开情报）；不含用户私密内容 | 低风险 |
| 网络副作用 | 本轮仅 1 次 `GET /health`；测试均用临时目录；`test_video_pipeline` 仅本地 lavfi | PASS |
| 测试误伤真实库 | `test_zcl_integration.py` 直接对真实 DB 采集；`test_lifecycle.py:164` 打开真实库 | **风险项**（IS-13） |

---

## 10. 测试证据与实际执行记录

### 10.1 本轮真实执行（命令 / 退出码 / 结果）

| # | 命令 | 退出码 | 结果 |
|---|---|---|---|
| E1 | `python tests\test_skillkit_contract.py` | 0 | PASS（枚举/两级去重/断点/退避/脱敏） |
| E2 | `python tests\test_techradar.py` | 0 | PASS（建表/去重/状态机/台账/持久化，临时库） |
| E3 | `python tests\test_registry.py` | 0 | PASS（14 项能力字段/状态枚举/5 适配文档） |
| E4 | `python tests\test_video_pipeline.py` | 0 | PASS（合成好片 PASS / 坏片 FAIL / dry-run 脱敏） |
| E5 | SQLite `mode=ro` 全表查询 | 0 | 15 表、103 entries、schema v3、FTS=NONE、tags=0 |
| E6 | `schtasks /Query /TN <4 tasks> /FO LIST /V` | 0 | 4 任务存在；daily Last Result=0；其余 267011（从未运行） |
| E7 | 单次 `GET https://radar.zichuanlan.top/health` | 200 | `ok=true, version=0.1.0, docker-readonly` |
| E8 | 静态 grep（编辑原语/DB 引用/日志/密钥） | 0 | 见 §3、§4、§9 |

### 10.2 本轮**故意未执行**的测试（只读纪律）

| 测试 | 原因 | 历史状态 |
|---|---|---|
| `tests/test_zcl_integration.py` | 第 19 行 `DB = 真实库`，会真实采集并写入/删除条目 | 历史报告称 13/13 PASS，本轮 NOT_TESTED |
| `tests/test_lifecycle.py` | 第 164 行 `IntelDB(REAL_DB)` 会执行迁移写入；副本段可跑但无法只读 | 历史报告称 36 项 PASS，本轮 NOT_TESTED |
| `healthcheck.py --out ...` | 会创建报告文件 | 历史 PASS |
| `scheduler.py --action status` | 会打开 IntelDB 并执行 `UPDATE schema_meta`（非纯只读） | 历史 PASS |

### 10.3 证据清单（按 Skill）

**爬虫**
- 文件：`00_crawl_Skills/SKILL.md`、`README.md`、`skills/web-scraping/01–08`
- 代码：无自有 runner；`_shared/skillkit/policy.py`、`manifest.py`
- 测试：E1
- 产物：无（本轮只读）
- 未验证：真实站点抓取、浏览器渲染、repos 可用性

**视频**
- 文件：`02_video_pipeline/SKILL.md`、4 个脚本
- 测试：E4（合成 fixture）
- 产物：临时目录（已销毁）
- 未验证：真实素材成片、真实参考视频、字幕/BGM/转场/导出

**情报**
- 文件：`03_techradar/SKILL.md`（v1.2.0）、7 脚本、DB 307,200 B
- 测试：E2、E5、E6、E7
- 产物：`TASK_REGISTRY.json`、`lifecycle_config.json`、DB 内 6 条 job_runs
- 未验证：Folo/Reddit 真实读取、weekly/monthly/quarterly 实跑、真实删除、FTS/标签检索

---

## 11. 问题清单

| ID | 所属 Skill/规则 | 问题描述 | 证据 | 影响 | 严重程度 | 建议方案 |
|---|---|---|---|---|---|---|
| IS-01 | 触发链（tech-radar 壳） | 客户端实际触发的 `tech-radar` 与本地情报库完全脱节，不含 DB/脚本/生命周期任何引用 | 客户端 SKILL 10,059 B（无 `sqlite/数据库/radar.zichuanlan/lifecycle` 命中）；canonical 03 为 15,057 B | 情报任务永远走 MCP/泛搜索；103 条库与 4 个定时任务对对话不可见，生命周期能力形同虚设 | **P0** | 让触发态 SKILL 指向 canonical：安装 03 或在 tech-radar 顶部加"库根 + 必读 03 SKILL + 启动自检" |
| IS-02 | 全局/发现机制 | 三个 canonical Skill 均不在任何客户端技能目录；`02`/`03` 无 description 被发现；`00_crawl` 无 description | Trae 目录仅 3 个技能；WorkBuddy 仅 crawl；工作区无 AGENTS.md | 自动路由不可达，只能靠用户口述绝对路径 | **P0** | 按客户端分别安装壳（含 description），或在全局规则写死路径路由 |
| IS-03 | 视频 | `02_video_pipeline` 只有素材/分析/QC/预览四个脚本，**无剪辑、字幕、配音、BGM、转场、导出实现** | 脚本列表 4 个；grep `drawtext/xfade/amix/loudnorm/libx264` 无命中 | 跨客户端无法产出成片；SKILL §0 的"ffmpeg 主链路"是空承诺 | **P1**（Trae 内 aitoearn 可替代，等效 P0） | 新增 `render.py`（字幕/转场/BGM/混音/导出）或明确标注"仅 Trae 可用" |
| IS-04 | 视频 | `E:\Trae_Video_Workspace\bgm.mp3` 与 `bgm\` 不存在 | `Test-Path` 均为 False；02 SKILL §6 自述 | 无声视频自动垫乐分支必然失败 | P1 | 放入授权 BGM 并登记来源/许可 |
| IS-05 | 情报/调度 | 仅 daily 实际运行过；weekly/monthly/quarterly 从未运行（Last Result 267011） | `schtasks /Query /V` 四任务；job_runs 仅 daily 有真实采集记录 | 周/月/季流程只有代码与注册，无运行证据 | P1 | 分别手动触发一次（dry-run 即可），写入 job_runs |
| IS-06 | 情报 | 分层阅读未落地：103 条 `read_state` 全为 `title_scanned` | 只读查询；无脚本 UPDATE read_state | "读了正文/评论"无法审计，覆盖率台账无数据支撑 | P1 | 给采集器加 read_state 升级；或明确标注该字段仅人工维护 |
| IS-07 | 情报 | 无全文/标签/时间/关联检索：无 FTS 表、tags 0 行、radar_query 仅 LIKE + 场景关键词 | `FTS: NONE`；`tags/entry_tags/relations` 全 0；脚本 L59–96 | 复杂问题只能关键词碰运气，无法按时间窗/标签/关系检索 | P1 | 建 FTS5 虚表 + 标签写入 + `--since/--tag/--related` 参数 |
| IS-08 | 情报 | Folo/Reddit 凭证缺失，5 个源只剩 3 个 | `folo token set: False`；`reddit id/secret: False`；sources 3 行 | 用户订阅源长期缺席，情报偏科 | P1（BLOCKED，需人工） | 用户补凭据；代码无需改 |
| IS-09 | 爬虫 | 库内无自有可执行采集器，真实采集验证依赖外部脚本 | `00_crawl_Skills` 无 .py（repos 除外） | "能抓"只有文档证据，无库内可复现 runner | P1 | 提供 `scripts/run_probe.py`（P0 四连）+ 一个真实站点 smoke |
| IS-10 | 规则冲突 | `tech-radar` 与 `material-sourcing-crawler` 都声称爬虫武器库；`aitoearn` 与 `02` 都声称剪辑发布 | 两个 description 文本 | 同一请求竞争触发，结果不稳定 | P1 | 明确分工：爬虫→material-sourcing；情报→tech-radar；视频执行→aitoearn；02 仅非 Trae |
| IS-11 | 双轨漂移 | canonical 03 与客户端 tech-radar 双份且不同源；crawl 也有两份（WorkBuddy 一致） | 10,059 vs 15,057 B；mtime 14:40 vs 22:27 | 改库不改壳，行为与文档长期背离 | P1 | 定"库为源"，加 `sync` 校验（哈希比对）到启动自检 |
| IS-12 | 测试 | 两套测试写真实库，非隔离 | `test_zcl_integration.py:19`、`test_lifecycle.py:164` | 误跑会改真实数据；审计/CI 不可重复 | P2 | 改为 `--db` 参数 + 临时副本，或加 `--allow-real-db` 开关 |
| IS-13 | 横切 | 共享脱敏日志 `loggingx` 零调用 | grep 无命中 | 无统一日志，排障靠 stdout | P2 | 在各脚本入口接 MaskedLogger，日志落 `_logs/<job>/` |
| IS-14 | 文档 | README 写"12 项能力"，实际 14；03 SKILL §3 写"Schema v2"，实际 v3；AGENTS.md 运行时路径仍旧 | 三处文本对比 | 误导后续 Agent 与人工 | P2 | 三处同步修正 |
| IS-15 | 情报 | `scheduler --action status` 会打开 IntelDB 并执行迁移 UPDATE，非纯只读 | 代码 `with IntelDB(DB) as db` | 违反"检查不应改库"原则，幂等审计失真 | P2 | status 改用 `mode=ro` 连接 |
| IS-16 | 情报 | 评分/保留/删除只在合成数据验证；真实库 purge_log=0、insights=0、snapshots=0 | 只读查询 | 真实数据下保护与清理未证明 | P2 | 用真实库副本跑一次完整 apply + restore 演练 |
| IS-17 | 视频 | QC 仅有合成 fixture 证据；无真实成片报告 | `_reports` 无 video_qc | 真实素材画质门禁未证明 | P2 | 用一段真实测试片跑 QC 并存档 |
| IS-18 | 视频/情报 | 发布仅 dry-run；正式发布依赖 aitoearn MCP，未验证连通 | `publish_preview` 无网络；aitoearn key 存在但未调用 | "能发布"仍是未证明状态 | P2（BLOCKED 边界内合理） | 获批后做一次草稿/沙盒验证 |
| IS-19 | 跨 Skill | 02 不引用 03，03 不调用 02，只有 `_shared` 共用 | grep 无交叉引用 | 无法"用情报指导视频选题/素材" | P2 | 在 02 Playbook 增加"选题参考 03 场景检索"的可选步骤 |
| IS-20 | 注册表 | C14 标 PASS，但 3/4 周期未运行 | 注册表 vs job_runs | 状态口径偏乐观 | P2 | 降为 PARTIAL 或注明"仅 daily 实证" |
| IS-21 | 通知 | `00_crawl_Skills` frontmatter 无 `description` | L1–10 | WorkBuddy 按描述匹配时可能不触发 | P2 | 补 description（含触发词） |
| IS-22 | 适配文档 | `claude-code` 适配无"已验证/待实测"标记 | 文档 grep 无标记 | 读者误以为已验证 | P3 | 补状态标记 |
| IS-23 | 配置 | lifecycle 配置与 policy 表双写无一致性校验 | 两处数据 | 改配置忘同步表会导致审计失真 | P3 | 加 `--check-config` 比对 |
| IS-24 | 检索 | `radar_query` 场景关键词写死在代码，未读 `project_profiles` | 代码 `SCENARIOS` vs config | 改画像需改代码，两处漂移 | P3 | 从 config 读场景 |
| IS-25 | 标签 | `tags/entry_tags` 表长期空置，无写入逻辑 | 0 行 | 表结构冗余 | P3 | 要么实现写入，要么在文档标注"预留" |

---

## 12. 优化建议（为什么 / 改哪里 / 改什么 / 怎么验 / 影响 / 回滚）

### 12.1 最高优先：打通触发链（IS-01 + IS-02）

- **为什么**：库再完整，模型不加载就等于零；这是当前唯一让全部情报能力失效的单点。
- **改哪里**：`C:\Users\26808\.trae-cn\skills\tech-radar\SKILL.md` 顶部（或新建 `03_techradar` 壳目录）。
- **改什么**：加 6 行"强制入口"：库根、必读 `D:\00_skiill_ku\03_techradar\SKILL.md`、启动自检命令、无 DB 时禁止声称读过订阅。
- **怎么验**：新会话问"上周有哪些值得关注的新项目"，观察是否引用 `radar_query.py` 或 DB 行数。
- **影响**：只加引用，不改旧流程；已有 MCP 模式保留。
- **回滚**：删除新增段落即可，原文件先备份。

### 12.2 视频闭环（IS-03）

- **为什么**：canonical 版不能产出成片，跨客户端迁移即失效。
- **改哪里**：`02_video_pipeline/scripts/render.py`（新增）。
- **改什么**：最小实现——concat + 字幕 drawtext + BGM amix + loudnorm + 9:16 crop + 导出 + 调用 `video_qc.py`。
- **怎么验**：合成 3 镜素材 → 渲染 10s → QC PASS；坏输入 → FAIL。
- **影响**：纯新增，不动现有 4 脚本。
- **回滚**：删除新文件。

### 12.3 检索能力（IS-07）

- **为什么**：当前只能关键词 LIKE，用户问"上周""标签""关联"时无法回答。
- **改哪里**：`_shared/skillkit/inteldb.py` + `03_techradar/scripts/radar_query.py`。
- **改什么**：FTS5 `entries_fts`（title/summary/content）+ 触发器；`--since/--until/--tag/--related` 参数；标签写入。
- **怎么验**：同一批数据分别用 LIKE 与 FTS 查询，比较召回；时间窗结果边界正确。
- **影响**：新增虚表，不改原表；旧查询保留。
- **回滚**：`DROP TABLE entries_fts` 即恢复。

### 12.4 测试隔离（IS-12）

- **为什么**：审计与 CI 不能改真实数据。
- **改哪里**：`tests/test_lifecycle.py`、`tests/test_zcl_integration.py`。
- **改什么**：统一 `--db` 参数，默认复制到 tempfile；真实库需显式 `--allow-real-db`。
- **怎么验**：跑测试前后对真实库做 `SELECT COUNT(*)` + mtime 比对，必须不变。
- **影响**：测试语义不变，只改连接目标。
- **回滚**：还原文件。

### 12.5 周期任务补验（IS-05）

- **为什么**：注册≠运行，必须有一次真实 job_runs 记录。
- **改哪里**：不改代码，执行 `lifecycle_run.py --job weekly|monthly|quarterly`（dry-run）。
- **怎么验**：`job_runs` 新增 3 行且 status=PASS；`schtasks` Last Result=0 仅对 trigger 生效。
- **影响**：只写运行记录，不删数据（apply_purge=false）。
- **回滚**：无需回滚（记录类数据）。

### 12.6 文档与口径（IS-14/20）

- **为什么**：三个数字（12/14/20）互相矛盾会误导下一个 Agent。
- **改哪里**：`README.md`、`03_techradar/SKILL.md` §3 标题、`AGENTS.md` L121、`CAPABILITY_REGISTRY.yaml` C14。
- **改什么**：12→14；Schema v2→v3；运行时路径改 `D:\00_toolbox`；C14 标 PARTIAL 并注明"仅 daily 实证"。
- **怎么验**：`test_registry.py` 通过 + 人工 grep 无旧数字。
- **影响**：纯文档。
- **回滚**：git/备份还原。

---

## 13. 优化优先级

| 优先级 | 事项 | 对应问题 | 理由 |
|---|---|---|---|
| 1 | 打通触发链（安装/引用 canonical 03、02） | IS-01/02 | 不做则后面全部无效 |
| 2 | 视频渲染闭环或明确能力边界 | IS-03 | 核心承诺与实现不符 |
| 3 | 补 BGM 授权文件 | IS-04 | 直接阻塞无声视频 |
| 4 | 周/月/季补一次真实运行 | IS-05 | 注册≠验证 |
| 5 | FTS/时间/标签检索 | IS-07 | 决定"能不能查得到" |
| 6 | 测试隔离 | IS-12 | 防止误伤真实数据 |
| 7 | 分层阅读落地或降级声明 | IS-06 | 决定台账可信度 |
| 8 | Folo/Reddit 凭据 | IS-08 | 用户侧阻塞 |
| 9 | 统一日志 | IS-13 | 排障与审计 |
| 10 | 文档校准 | IS-14/20/21/22 | 降低下一个 Agent 的误解 |

---

## 14. 建议修改的文件清单

| 文件 | 改动类型 | 目的 |
|---|---|---|
| `~/.trae-cn/skills/tech-radar/SKILL.md` | 追加 | 指向 canonical 03 + 启动自检（IS-01） |
| `~/.trae-cn/skills/tech-radar/` 或新建 `03_techradar` 壳 | 新增 | 让 03 被扫描到（IS-02） |
| `~/.trae-cn/user_rules/rule-*.md` | 追加 | 爬虫/视频/情报三类意图分流（IS-10） |
| `02_video_pipeline/scripts/render.py` | 新增 | 补齐渲染闭环（IS-03） |
| `02_video_pipeline/SKILL.md` | 修改 | 未实现能力如实标注（IS-03） |
| `03_techradar/scripts/radar_query.py` | 修改 | 时间/标签/关联检索（IS-07） |
| `_shared/skillkit/inteldb.py` | 追加 | FTS5 与标签写入（IS-07） |
| `tests/test_lifecycle.py`、`tests/test_zcl_integration.py` | 修改 | 隔离真实库（IS-12） |
| `README.md`、`AGENTS.md`、`03_techradar/SKILL.md` | 修改 | 数字/版本/路径校准（IS-14） |
| `CAPABILITY_REGISTRY.yaml` | 修改 | C14 状态与验证口径（IS-20） |
| `00_crawl_Skills/SKILL.md` | 修改 | 补 `description`（IS-21） |
| `adapters/claude-code/README.md` | 修改 | 补验证状态（IS-22） |

---

## 15. 建议新增或删除的规则清单

**新增**

1. 全局规则增加分流句：抓取/反爬 → `material-sourcing-crawler`（内含 `00_crawl_Skills`）；技术选型/情报 → `tech-radar`；剪辑/发布 → `aitoearn`；跨客户端视频 → `02_video_pipeline`。
2. `tech-radar` 壳新增"先读 canonical 03 + 启动自检"硬规则。
3. 新增"测试不得写真实库，除非显式 `--allow-real-db`"。
4. 新增"Skill 更新后必须同步客户端壳并校验哈希"。
5. 新增"情报推荐必须带来源/时间/链接，否则视为未完成"（canonical 已有，壳内缺）。

**删除/收敛**

1. 从 `tech-radar` 描述中删除"重型爬虫武器库"表述，避免与素材采集抢触发。
2. 删除/合并 `02_video_pipeline` 与 `aitoearn` 重复的"素材发现"描述，明确谁是执行者。
3. 不再新增第二套检索实现；统一走 `radar_query.py`。

---

## 16. 暂时不应该修改的部分

1. **`00_crawl_Skills/skills/web-scraping/01–07` 正文**：P0–P5 方法论与故障表是经实践沉淀的资产，本轮无证据表明有错。
2. **`_shared/skillkit` 的既有契约**：manifest/policy/inteldb 已被三条链路复用，改动会连带 6 套测试。
3. **`03_techradar` 的 Schema v3 与生命周期四道闸**：结构已验证，真实库零删除，暂不需要再动。
4. **`publish_preview.py` 的 dry-run 边界**：符合安全要求，不应为了方便而放开。
5. **7 个 `repos/` 收藏仓库**：本轮未使用，不应清理或升级。
6. **`.venv` 与浏览器运行时**：不动，避免断路径。

---

## 17. 仍需人工处理的阻塞项

| 阻塞项 | 类型 | 需要做什么 | 影响范围 |
|---|---|---|---|
| Folo 会话令牌 | 凭据 | 登录 folo 取 session 填入 `mcpServers.folo.env.FOLO_SESSION_TOKEN` | TechRadar 订阅源（IS-08） |
| Reddit API 凭据 | 凭据 | `developers.reddit.com/app-registration` 建 app 填 ID/SECRET | TechRadar 社区源（IS-08） |
| BGM 音频与授权 | 素材/版权 | 放入 `E:\Trae_Video_Workspace\bgm.mp3` 并登记许可 | 视频自动垫乐（IS-04） |
| 真实成片 QC | 测试素材 | 提供一段有权处理的参考片/成片 | 视频 QC 真实性（IS-17） |
| 客户端壳安装授权 | 决策 | 是否把 02/03 安装进 Trae/WorkBuddy 技能目录 | 触发链（IS-01/02） |
| 真实发布验证 | 授权 | 获批后做一次草稿/沙盒发布 | 发布链路（IS-18） |
| Windows 任务"不登录也运行" | 系统权限 | 需管理员并保存凭据 | 定时任务可靠性 |

---

## 18. 本轮审计纪律声明

- 本轮**只创建了本报告一个文件**（`D:\00_skiill_ku\AUDIT_REPORTS\THREE_SKILLS_AUDIT_2026-11-17.md`）。
- 未修改、删除、覆盖任何既有文件；未安装依赖；未创建/修改/删除 Windows 计划任务；未做真实发布；未打印任何凭据值。
- 数据库仅以 `mode=ro` 打开查询；计划任务仅 `/Query`。
- 全部 `PASS` 结论均对应第 10 节的真实命令与退出码；无证据项一律标 `NOT_TESTED` / `NOT_IMPLEMENTED` / `BLOCKED`。
- 涉及"模型是否会自动触发"的判断属于**规则静态分析**，未做真实路由实验，已在 §6 逐行标注。
