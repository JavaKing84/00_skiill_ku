# 我的 Skill 库（D:\00_skiill_ku）

按领域分目录的个人 AI 能力库。每个域一个文件夹，自带 `SKILL.md`（给模型看）和 README（给人看）；
脚本、SQLite 情报库、浏览器内核、测试全部在库内，换客户端时整库可搬。

> 重构时间：2026-11-21　·　结构版本：01–06 域目录
> 换客户端或接手前，先读 [AGENTS.md](./AGENTS.md)（模型入口 / 路由表 / 重建 SOP）。

---

## 目录总览

| 目录 | 领域 | 里面有什么 | 入口 |
|---|---|---|---|
| `01_crawler\` | 爬虫 / 反爬 | P0–P5 协议、WS-01~08 八篇分册、7 个收藏仓库、**Playwright + Camoufox 内核（3.8 GB）** | [SKILL.md](./01_crawler/SKILL.md) |
| `02_jobsearch\` | 求职 | job_radar 源仓库 + 已安装技能壳副本 + 运行时说明 | [README.md](./02_jobsearch/README.md) |
| `03_video\` | 视频 | 素材验证 / 参考分析 / 渲染 / QC / 发布 dry-run 等 24 个脚本 + 素材下载器 + aitoearn 14 子技能 | [SKILL.md](./03_video/SKILL.md) |
| `04_design\` | 设计 / PPT | 花叔 Design v3.4.2：HTML 原型、Deck、信息图、导出可编辑 PPTX | [SKILL.md](./04_design/SKILL.md) |
| `05_school\` | 学校技能 | iDeal 工作室 70 个 SKILL.md：需求 / 数据库 / SQL 转后端 / 原型转应用 / Go / Java / 安全 / 科研 —— 逐个说明见 [SKILLS_GUIDE.md](./05_school/SKILLS_GUIDE.md) | [SKILL.md](./05_school/SKILL.md) |
| `06_techradar\` | 技术情报 | 23 个采集/检索/维护脚本 + SQLite 情报库（1,353 条 / 255 篇正文）+ 4 个计划任务 | [SKILL.md](./06_techradar/SKILL.md) |
| `07_bossauto\` | BOSS 自动投递 | Chrome CDP + boss-helper：额度计划、资产校验、重试与额度用尽安全挂起 | [SKILL.md](./07_bossauto/SKILL.md) |
| `00_library_architect\` | 库维护 | 审计、重构、迁移本库自身的协议 | [SKILL.md](./00_library_architect/SKILL.md) |
| `_shared\skillkit\` | 共享底座 | 去重、限速、清单、情报库、FTS、生命周期等 13 个模块 | [README.md](./_shared/README.md) |
| `adapters\` | 客户端适配 | trae / workbuddy / claude-code / loomi / generic-agent / 飞书平替 | [README.md](./adapters/README.md) |
| `tests\` | 测试 | 13 套测试 + 触发用例 | [TEST_REPORT.md](./_reports/TEST_REPORT.md) |

根目录另有：`AGENTS.md`（模型入口）、`CAPABILITY_REGISTRY.yaml`（27 项能力与实测状态）、
`INSTALLATION_GUIDE.md`（新机器重建）、`VERIFICATION_RULES.md`（验收语义）、`CHANGELOG.md`（变更历史）。

---

## 标准技能索引（`skills/`，2026-11-25 新增）

`skills/` 是面向 npx / Agent 客户端的标准聚合层：只放 `SKILL.md` + `CHANGELOG.md`，
通过相对路径映射到原有域目录，**不移动、不复制业务脚本**，老命令原地可用。

| 技能 | 版本 | 领域 | 触发词（节选） | 映射到 |
|---|---|---|---|---|
| `03-video-pipeline` | 1.0.0 | 视频 | 剪辑 / 成片 / 字幕 / 配音 / QC / 发布预览 | `03_video/` |
| `01-crawler` | 1.0.0 | 爬虫 | 抓取 / 采集 / 反爬 / 登录态 / 找素材 | `01_crawler/` |
| `60s-api` | 1.0.0 | 数据源 | 每日新闻 / 热搜 / 天气 / 农历 / 翻译 | `skills/data/60s-api/scripts/fetch.py` |

```powershell
# 机器可读索引（扫描 skills/ 自动生成）
& $PY _shared\build_skills_index.py        # 输出 skills.json

# npx 识别验证
npx -y skills add D:\00_skiill_ku --list   # 实测识别 10 个技能

# 60s API 真实调用（主域名失败会自动回退公共实例）
& $PY skills\data\60s-api\scripts\fetch.py --endpoint 60s
```

`.agents/skills/` 下已建立三个目录联接（Junction）指向 `skills/`，供只认 `.agents/skills/` 约定的客户端加载。

---

## 怎么用

**1）直接说需求（自动触发）**
装在 Trae 的 4 个壳会命中关键词：

- “抓一下这个网站 / 批量下载素材” → `01_crawler` + 素材下载器
- “最近 VLA 有什么新进展 / 调研这个开源项目” → `06_techradar`
- “把素材剪成 60 秒竖屏 / 检查成片黑屏” → `03_video`
- “做个 PPT / App 原型 / 信息图” → `04_design`

`02_jobsearch` 和 `05_school` 没有装壳，需要点名文件，例如“按 `05_school\SKILL.md` 做数据库设计”。

**2）手动点菜（最可控）**
直接引用 `SKILL.md` 路径，或自己跑脚本：

```powershell
$PY = "D:\00_skiill_ku\.venv\Scripts\python.exe"

# 查本地情报（只读）
& $PY D:\00_skiill_ku\06_techradar\scripts\radar_query.py `
  --db D:\00_skiill_ku\06_techradar\data\techradar.db --since 2026-11-01 --limit 20

# 系统 / 数据库 / 定时任务状态
& $PY D:\00_skiill_ku\06_techradar\scripts\scheduler.py --action status

# 成片质检
& $PY D:\00_skiill_ku\03_video\scripts\video_qc.py --video 成片.mp4 --out qc\
```

**3）后台自跑**
四个 Windows 计划任务（daily / weekly / monthly / quarterly），入口在 `06_techradar\scripts\tasks\`。
下次 `TechRadar_Daily` 触发时间用 `scheduler.py --action status` 查。

---

## 现在能做什么，不能做什么

| 状态 | 能力 |
|---|---|
| ✅ 可用 | 公开源采集与去重、FTS5 检索、正文回源（255 篇 / 243 ok）、生命周期维护、视频渲染与 QC、花叔 Deck 导出、爬虫协议与内核、BOSS 投递计划与安全挂起 |
| ⚠️ 半通 | 真实发布（只有 dry-run）、受限安全站（The Record / Packet Storm 仍被拦）、双通道的认证通道、BOSS 实际投递成功率（受平台额度/登录态影响） |
| ❌ 阻塞 | Reddit 出口 IP 被 403（浏览器登录态可读部分技术板块）；Folo 官方令牌未配置（当前走浏览器登录态） |
| ⚠️ 运维注意 | `TechRadar_Daily` 已修复假空转（11-24 run_id=15 inserted=150）；11-23/11-24 早班因主机休眠漏跑，已开启 StartWhenAvailable / WakeToRun |

---

## 这次重构做了什么

| 旧路径 | 新路径 |
|---|---|
| `D:\00_skiill_ku\00_crawl_Skills` | `D:\00_skiill_ku\01_crawler` |
| `D:\00_skiill_ku\01_jobsearch_Skills` | `D:\00_skiill_ku\02_jobsearch` |
| `D:\00_skiill_ku\02_video_pipeline` | `D:\00_skiill_ku\03_video` |
| `D:\00_skiill_ku\04_huashu_design` | `D:\00_skiill_ku\04_design` |
| `D:\00_skiill_ku\05_idealskills` | `D:\00_skiill_ku\05_school` |
| `D:\00_skiill_ku\03_techradar` | `D:\00_skiill_ku\06_techradar` |
| `D:\00_skiill_ku\00_personal_ai_skill_architect` | `D:\00_skiill_ku\00_library_architect` |
| `D:\00_toolbox\00_crawl_Skills\{Playwright,Camoufox}` | `D:\00_skiill_ku\01_crawler\runtime\{Playwright,Camoufox}` |

- 素材下载器与 aitoearn 文档已复制进 `03_video`（库内为源，客户端 `skills\` 为安装壳）。
- 迁移前快照与逐条映射在 `_backup\20261121_refactor\`（`MOVE_MANIFEST.csv`）。
- `_reports\` 与 `AUDIT_REPORTS\` 中的旧路径是历史记录，未追改。
