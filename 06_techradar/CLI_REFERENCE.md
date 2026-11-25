# 06_techradar 脚本参数参考（由 scripts/*.py 自动提取）

> 本文件由脚本的 argparse 定义自动生成，**以代码为准**。
> 生成时间：2026-11-24。修改脚本参数后请重新生成本文件，避免文档与实现漂移。

## `collect_folo.py`

collect_folo.py — 通道 B-1：Folo（Follow）认证采集适配器。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  |  |
| `--limit` |  | 默认: `20` |
| `--max-feeds` |  | 默认: `10` |
| `--report` |  |  |

## `collect_github_issues.py`

collect_github_issues.py — 排障型情报源：GitHub Issues 搜索。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  |  |
| `--limit` |  | 默认: `8` |
| `--queries` |  |  |
| `--report` |  |  |

## `collect_public.py`

collect_public.py — 公开情报源采集（TechRadar 降级链，Phase 3.2/3.5）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  | 必填 |
| `--source` |  | 可选值: hn / github / both；默认: `both` |
| `--limit` |  | 默认: `10` |
| `--query` | GitHub 搜索查询（仅 source=github/both 时使用） | 默认: `created:>2025-01-01 stars:>1000` |

## `collect_public_suite.py`

collect_public_suite.py — 通道 A 编排器：零凭证公开情报采集。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  |  |
| `--limit` | 每个来源最多取多少条 | 默认: `20` |
| `--only` | 逗号分隔的 source_id 白名单 |  |
| `--report` |  |  |

## `collect_reddit.py`

collect_reddit.py — 通道 B-2：Reddit 官方 Data API OAuth 适配器。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  |  |
| `--subreddits` |  | 默认: `coolgithubprojects,BestGitHubRepos,LocalLLaMA,MachineLearning` |
| `--limit` |  | 默认: `25` |
| `--report` |  |  |

## `collect_reddit_topics.py`

collect_reddit_topics.py — 排障型情报源：Reddit 技术板块讨论。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  |  |
| `--subreddits` |  | 默认: `webscraping,Python` |
| `--limit` |  | 默认: `15` |
| `--report` |  |  |

## `collect_stackoverflow.py`

collect_stackoverflow.py — 排障型情报源：Stack Overflow 指定 Tag。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  |  |
| `--tags` |  |  |
| `--limit` |  | 默认: `10` |
| `--report` |  |  |

## `collect_topic.py`

collect_topic.py — 主题驱动的公开情报采集（把外部技术发现注入 TechRadar）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  |  |
| `--topic` |  | 必填 |
| `--source` |  | 可选值: hn / github / both；默认: `both` |
| `--limit` |  | 默认: `10` |
| `--report` |  |  |

## `collect_zcl.py`

collect_zcl.py — 资源雷达（radar.zichuanlan.top）二级聚合源采集器。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  | 必填 |
| `--max-items` | 本次最多入库条目数（分页总量上限） | 默认: `60` |
| `--page-size` |  | 默认: `40` |
| `--detail-limit` | 最多补拉多少条详情正文 | 默认: `10` |
| `--kinds` |  |  |
| `--categories` |  |  |
| `--report` | 可选：把本次运行统计写为 JSON |  |

## `fetch_bodies.py`

fetch_bodies.py — 正文回源抓取（RSS 只是目录，正文必须回源拿）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  | 必填 |
| `--category` | 按分类抓取；空字符串表示全部（PowerShell 会吞掉空串，建议用 --all） | 默认: `security` |
| `--all` | 抓取全部分类（等价 --category=） | 开关 |
| `--since` |  |  |
| `--limit` |  | 默认: `20` |
| `--retry-failed` |  | 开关 |
| `--stats` |  | 开关 |
| `--sync-read-state` | 回填历史正文的 read_state：status=ok 的条目推进到 content_fetched | 开关 |
| `--report` |  |  |
| `--no-browser` | 禁用无头浏览器（第三级），纯 HTTP 环境用 | 开关 |

## `healthcheck.py`

healthcheck.py — TechRadar 数据源健康检查（Phase 3.1）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--mcp-config` |  |  |
| `--mcp-folo` |  | 可选值: ok / auth_required / unavailable / untested；默认: `untested` |
| `--mcp-reddit` |  | 可选值: ok / auth_required / unavailable / untested；默认: `untested` |
| `--out` |  | 必填 |

## `import_knowledge.py`

import_knowledge.py — 把实战排障知识直接写入 TechRadar 情报库。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  | 必填 |
| `--dry-run` |  | 开关 |

## `ingest_case_notes.py`

ingest_case_notes.py — 把实战案例写成 knowledge_base 条目（可重复执行，按 URL+标题去重）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  |  |

## `lifecycle_run.py`

lifecycle_run.py — TechRadar 生命周期任务执行器（daily / weekly / monthly / quarterly）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--job` |  | 必填；可选值: daily / weekly / monthly / quarterly |
| `--db` |  |  |
| `--config` |  |  |
| `--apply` | 允许真实删除（仍需 config.apply_purge=true） | 开关 |
| `--no-collect` | daily 跳过网络采集 | 开关 |
| `--report-dir` |  |  |

## `radar_query.py`

radar_query.py — 本地情报检索（SQLite 真实查询，不联网）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  | 必填 |
| `--scenario` | 预设场景：ai-robot / small-model / douyin-growth / ai-agent |  |
| `--text` | 自由文本检索 |  |
| `--keywords` | 逗号分隔关键词（与 --text 等价） |  |
| `--since` | 起始发布时间，含，如 2026-11-01 |  |
| `--until` | 截止发布时间，含 |  |
| `--tag` | 标签过滤，逗号分隔 |  |
| `--source` | 来源过滤，逗号分隔 |  |
| `--related` | 与指定 entry_id 关联的条目 |  |
| `--engine` |  | 可选值: auto / fts5 / like；默认: `auto` |
| `--intent` | 技术意图过滤：tech 时优先知识库/Issues/SO/技术社区，过滤安全新闻 | 可选值: auto / tech / news；默认: `auto` |
| `--order` |  | 可选值: published_desc / cross_source_desc / oldest；默认: `published_desc` |
| `--init-fts` | 创建并回填 FTS 索引 | 开关 |
| `--mark-fetched` | 返回正文时推进 read_state 到 content_fetched | 开关 |
| `--limit` |  | 默认: `15` |
| `--out` |  |  |

## `radar_read.py`

radar_read.py — 按需深度阅读入口（title_scanned → content_fetched → content_read → analyzed）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  |  |
| `--entry-id` |  | 默认: `[]` |
| `--query` |  |  |
| `--tag` |  |  |
| `--since` |  |  |
| `--limit` |  | 默认: `5` |
| `--fetch` | 抓取候选条目的正文（默认只列候选） | 开关 |
| `--mark-read` | 对已有正文的条目推进到 content_read | 开关 |
| `--mark-analyzed` | 配合 --claim 推进到 analyzed 并写 insights | 开关 |
| `--claim` | 已形成的有证据结论（写入 insights） |  |
| `--dry-run` | 只展示将要做什么，不写库 | 开关 |
| `--out` |  |  |

## `scheduler.py`

scheduler.py — TechRadar 定时任务注册器（Windows 任务计划程序）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--action` |  | 必填；可选值: status / install / remove / trigger-test |

## `source_status.py`

source_status.py — 数据源注册表巡检与状态清单。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  |  |
| `--json` | 输出 JSON 报告路径 |  |

## `tagging.py`

tagging.py — 特征标签自动打标（排障型情报）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--db` |  | 必填 |
| `--hours` | 最近 N 小时入库的条目；0 表示全量 | 默认: `6` |
| `--all` | 全量补标 | 开关 |
| `--batch` |  | 默认: `3000` |
