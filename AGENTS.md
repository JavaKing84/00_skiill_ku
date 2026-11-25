# AGENTS.md — 技能库总入口（模型先读这份）

> 库根：`D:\00_skiill_ku`　·　结构版本：2026-11-21 重构（01–06 域目录）
> 关系：**库是源，客户端 `skills\` 目录是安装壳**。冲突以库为准，改完库再同步壳。
> 这份文件只写模型猜不到的东西：路径、命令、参数、状态、坑。

---

## 0. 三条硬规则

1. **先路由，再读文件，最后执行**。命中哪一行，就用 Read 打开对应 `SKILL.md`；不要凭记忆回答。
2. **没有产物不算完成**。采集要有落盘文件与条数，渲染要有可解析的成片，情报要入 SQLite 并可检索，质检要有 verdict。
3. **状态只认实测**。`PASS / PARTIAL / BLOCKED / NOT_TESTED` 必须能在 `_reports\`、`_logs\` 或数据库里找到证据；缺凭证就写 BLOCKED，不许假装读过。

---

## 1. 路由表

| 请求特征 | 域 | 先读 | 执行入口 |
|---|---|---|---|
| 抓网站 / 采集正文列表 / 批量下载 / 反爬 403/429 / 登录态 / 找图片视频素材 | `01_crawler` | `01_crawler\SKILL.md` | `03_video\material-sourcing-crawler\scripts\material_crawler.py` |
| 求职 / 岗位 / 简历 / jobradar | `02_jobsearch` | `02_jobsearch\README.md` + `job_radar\SKILL.md` | 运行时在 `D:\新建文件夹 (2)\jobradar\`（不要搬） |
| 剪辑 / 字幕 / 配音 / 转码 / 成片质检 / 多平台发布 / 找素材 | `03_video` | `03_video\SKILL.md` | `~\.trae-cn\skills\aitoearn` + `03_video\scripts\*.py` |
| App 原型 / PPT / 信息图 / 封面 / HTML 页面 / 动效 | `04_design` | `04_design\SKILL.md` | `04_design\scripts\`（`pptx_from_rendered.py`、`export_deck_pptx.mjs` 等） |
| 需求分析 / PRD / 数据库设计 / SQL 转后端 / 原型转应用 / Go / Java / 安全 / 科研论文 | `05_school` | `05_school\SKILL.md` | 按该文件里的场景表进子目录 |
| 技术选型 / 趋势 / 新模型 / 开源项目评估 / 本地情报检索 / 会议纪要 | `06_techradar` | `06_techradar\SKILL.md` | `06_techradar\scripts\*.py` |
| BOSS 自动投递 / 自动打招呼 / 今日投递额度 / 投递中断排查 | `07_bossauto` | `07_bossauto\SKILL.md` + `README.md` | `07_bossauto\run_scheduled.ps1` / `bossctl.js` |
| 维护技能库本身（审计 / 重构 / 迁移） | `00_library_architect` | `00_library_architect\SKILL.md` | 按该文件协议执行 |

**易混边界**

- 只打开一篇网页、总结已给文章 → 不触发 01，直接做。
- 只分析视频内容、不产出成片 → 不触发 03 全流程。
- 只讨论技术概念 → 不触发 06。
- `05_school\design\huashu-design` 是 v3.0 旧快照，设计一律走 `04_design`。

---

## 2. 目录地图（重构后）

```
D:\00_skiill_ku\
├── AGENTS.md                  ← 本文件（模型入口）
├── README.md                  ← 人看的说明
├── 00_library_architect\      ← 库自身审计 / 重构技能
├── 01_crawler\                ← 爬虫：P0–P5 协议、WS-01~08、7 个收藏仓库
│   ├── runtime\               ← Playwright + Camoufox 浏览器内核（3.8 GB）
│   ├── skills\web-scraping\   ← 8 篇分册
│   ├── scripts\               ← extract_article / build_platform_matrix 等
│   └── reports\
├── 02_jobsearch\              ← job_radar 源仓库 + 技能壳副本
├── 03_video\                  ← 视频生产与素材
│   ├── scripts\               ← verify_asset / reference_analyze / render / video_qc / publish_preview
│   ├── material-sourcing-crawler\ ← 素材下载执行器（库内源）
│   └── aitoearn\              ← 14 子技能文档（库内副本）
├── 04_design\                 ← 花叔 Design v3.4.2（HTML → 原型 / Deck / PPTX / 视频）
├── 05_school\                 ← iDeal 工作室 70 个 SKILL.md（git 快照）
├── 06_techradar\              ← 情报系统：23 脚本 + SQLite + 4 个计划任务
│   ├── data\techradar.db
│   └── scripts\tasks\*.cmd
├── 07_bossauto\               ← BOSS 自动投递：CDP + boss-helper + 额度计划 / 安全挂起
│   ├── SKILL.md               ← 模型入口（输入/输出/重试/额度策略）
│   └── tests\test_pipeline.js ← 离线最小链路测试（10 项）
├── _shared\skillkit\          ← 13 个共享模块（去重 / 限速 / 清单 / DB / FTS / 生命周期）
├── adapters\                  ← trae / workbuddy / claude-code / loomi / generic-agent / 飞书平替
├── tests\                     ← 13 套测试 + trigger_cases.yaml
├── _reports\  _logs\          ← 测试、健康检查、任务日志
├── _backup\                   ← 历史备份（含 20261121_refactor 迁移前快照与 MOVE_MANIFEST.csv）
└── .venv\                     ← 项目隔离 Python 环境
```

**旧路径已全部失效**（不要再引用）：`00_crawl_Skills`→`01_crawler`、`01_jobsearch_Skills`→`02_jobsearch`、`02_video_pipeline`→`03_video`、`03_techradar`→`06_techradar`、`04_huashu_design`→`04_design`、`05_idealskills`→`05_school`、`00_personal_ai_skill_architect`→`00_library_architect`、`D:\00_toolbox\00_crawl_Skills`→`01_crawler\runtime`。
`_reports\`、`AUDIT_REPORTS\` 里的旧路径是历史快照，不追改。

---

## 3. 运行时与环境

| 项 | 值 | 验证 |
|---|---|---|
| 浏览器内核 | `D:\00_skiill_ku\01_crawler\runtime\Playwright` | 环境变量 `PLAYWRIGHT_BROWSERS_PATH` 已指向它 |
| Chromium | `...\Playwright\chromium-1243\chrome-win64\chrome.exe` | 文件存在 |
| Camoufox | `...\runtime\Camoufox` | 内核在，Python SDK 未装 |
| Python | `D:\00_skiill_ku\.venv\Scripts\python.exe` | `--version` |
| ffmpeg / ffprobe | PATH 内 | `ffmpeg -version` |
| 字体 | `C:\Windows\Fonts\msyhbd.ttc` | 文件存在 |
| 情报库 | `06_techradar\data\techradar.db`（schema v4） | 1,353 entries / 255 bodies（243 ok） |
| 视频工作区 | `E:\Trae_Video_Workspace` | 素材与成片 |

> 当前会话若继承的是旧环境变量，重启客户端后 `PLAYWRIGHT_BROWSERS_PATH` 才全局生效；脚本内已写死新默认路径，不依赖环境变量也能跑。

---

## 4. 库与壳的同步

已装壳（自动触发用）：

| 客户端 | 壳目录 | 对应库内源 |
|---|---|---|
| Trae | `~\.trae-cn\skills\tech-radar` | `06_techradar\SKILL.md` |
| Trae | `~\.trae-cn\skills\aitoearn` | `03_video\aitoearn` |
| Trae | `~\.trae-cn\skills\material-sourcing-crawler` | `03_video\material-sourcing-crawler` |
| Trae | `~\.trae-cn\skills\huashu-design` | `04_design\SKILL.md` |
| WorkBuddy | `~\.workbuddy\skills\` 8 个 | 见 `README.md` |

同步检查：

```powershell
D:\00_skiill_ku\.venv\Scripts\python.exe D:\00_skiill_ku\tests\skill_sync_check.py
```

---

## 5. 当前真实状态（2026-11-24 实测）

- **PASS**：公开源采集与去重、FTS5 检索、正文回源（255 篇 / 243 ok）、情报生命周期、视频渲染与 QC、花叔 Deck 导出、爬虫协议与内核路径、BOSS 投递计划与额度用尽安全挂起。
- **PARTIAL**：真实发布（只做 dry-run）、`sec_restricted`（The Record / Packet Storm 仍被拦）、双通道（通道 B 凭据未配置，Folo 走浏览器登录态）、BOSS 实际投递成功率（受平台额度/登录态影响）。
- **BLOCKED**：Reddit 出口 IP 403（部分技术板块可经浏览器登录态读取）；Folo 官方令牌未配置。
- **运维注意**：`TechRadar_Daily` 的假空转已修复（11-24 run_id=15：collected=310 / inserted=150）；11-23、11-24 早班因主机休眠漏跑，已开启 StartWhenAvailable / WakeToRun，下次触发 11-25 07:30。
- **阅读台账**：`fetch_bodies.py` 成功抓取后会自动推进 `read_state=content_fetched`；历史 242 篇已回填，当前 243 篇 ok，`--sync-read-state` 可幂等重跑。
- **不要声称**：读到了用户订阅、已经公开发布、已经删除了情报（`apply_purge=false`）、BOSS 已全量投递成功。

---

## 6. 常用命令

```powershell
$PY = "D:\00_skiill_ku\.venv\Scripts\python.exe"

# 系统 / 数据库 / 定时任务状态
& $PY D:\00_skiill_ku\06_techradar\scripts\scheduler.py --action status

# 本地情报检索（只读）
& $PY D:\00_skiill_ku\06_techradar\scripts\radar_query.py `
  --db D:\00_skiill_ku\06_techradar\data\techradar.db --since 2026-11-01 --limit 20

# 成片质检
& $PY D:\00_skiill_ku\03_video\scripts\video_qc.py --video <成片> --out <QC目录>

# 采集（写库，先确认再跑）
& $PY D:\00_skiill_ku\06_techradar\scripts\collect_public_suite.py --limit 20

# 回归测试（离线优先）
& $PY D:\00_skiill_ku\tests\test_skillkit_contract.py
& $PY D:\00_skiill_ku\tests\test_techradar.py
& $PY D:\00_skiill_ku\tests\test_lifecycle.py

# 全量 13 套（PENDING 不算故障，FAIL 才非 0）
& $PY D:\00_skiill_ku\tests\run_all.py
```

---

## 7. 新客户端重建 SOP

1. 复制整个 `D:\00_skiill_ku`（`runtime\` 体积大，可单独拷）。
2. 装运行时：Python 3.11+、Node LTS、ffmpeg、git；`pip install -r requirements.txt`。
3. 设 `PLAYWRIGHT_BROWSERS_PATH=D:\00_skiill_ku\01_crawler\runtime\Playwright`。
4. 挂 MCP：`aitoearn-cn`（HTTP + `X-Api-Key`）、`youdao-note`、`folo`、`reddit`（后两者缺凭证即 BLOCKED）。
5. 把本文件的路由表写进新客户端的 system prompt / rules；没有自动发现机制的客户端，规定“命中后先 Read 对应 SKILL.md”。
6. 跑第 6 节命令 + `tests\skill_sync_check.py`，全绿再交付。

---

## 8. 改动检查清单（改路径 / 改目录后必做）

- [ ] 库内脚本：全库搜索旧目录名，无残留（排除 `_backup`、`_reports`、`AUDIT_REPORTS`、`05_school`、`04_design`、`runtime`、`repos`）
- [ ] 技能壳 4 个 + WorkBuddy 8 个的 `SKILL.md`
- [ ] 用户规则 `~\.trae-cn\user_rules\*.md`
- [ ] 计划任务：`scheduler.py --action install` 后 `--action status` 四条路径指向新目录
- [ ] `PLAYWRIGHT_BROWSERS_PATH`
- [ ] `CAPABILITY_REGISTRY.yaml`、`INSTALLATION_GUIDE.md`
- [ ] 跑测试；把结果写进 `_reports\`

---

## 9. 红线

- 不编造 URL、Star、发布时间、下载量；取不到写「未取得」。
- 不裸 HTTP 死磕反爬站；先读 `01_crawler\SKILL.md` 的 P0–P5。
- 不在文件、日志、回答里打印 Token / Cookie / API Key。
- 不真实公开发布视频或文章；发布只做 `publish_preview.py` dry-run。
- 没有工具却说「我已经读了 / 已经发布了 / 已经删了」= 最严重违规。
