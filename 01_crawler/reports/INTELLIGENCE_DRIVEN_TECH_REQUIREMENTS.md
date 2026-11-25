# 情报驱动的爬虫能力需求（Phase 1 产出）

- 生成时间：2026-11-18 01:35
- 数据来源：本地 TechRadar SQLite（真实查询）+ 主题检索补采（HN / GitHub 公开接口）

## 1. 本地存量检索结果（先查本地）

| 关键词 | 命中条数 |
|---|---|
| scrap / crawl / playwright / trafilatura / firecrawl / crawlee / anti-bot | **0** |
| browser | 2 |
| bilibili | 2 |
| selector | 1 |
| douyin / xiaohongshu | 0 |

结论：**整改前本地情报库对爬虫技术几乎空白**，无法支撑"情报驱动"的能力规划。
这不是推断，是 `SELECT COUNT(*) ... LIKE` 的真实计数。

## 2. 缺口补采（主题检索，真实入库）

用新增的 `06_techradar/scripts/collect_topic.py` 按主题从 HN + GitHub 公开接口补采：

| 主题 | 抓取 | 新增入库 | 去重 |
|---|---|---|---|
| web scraping | 16 | 14 | 2 |
| crawler | 16 | 14 | 2 |
| browser automation | 16 | 15 | 1 |
| **合计** | 48 | **43** | 5 |

库内条目：346 → **389**。新增均带原始链接、发布时间、来源与热度字段。

## 3. 情报映射出的能力需求（按真实条目）

| 需求 | 情报依据（真实条目） | 对应实现 |
|---|---|---|
| 渲染层判定（SSR / SPA / 需登录） | Scrapling / crawl4ai / browser-use 均以"自动识别页面形态"为核心卖点 | `probe_site.py` 的 `render_layer` / `structured_data` |
| 正文抽取与降级 | trafilatura（7.1k★）与 readability 路线并存 | `extract_article.py` 三引擎 |
| 登录态复用 | browser-use（121k★）证明"复用真实会话"是主流需求 | `probe_logged_in.py`（授权 + 不导出凭据） |
| 平台风控识别 | 抖音/小红书类目在 HN 讨论中反复出现"风控/签名" | 探测阻断词 + 如实 BLOCKED |
| 渲染后取数据 | crawl4ai（87k★）强调 JS 渲染 | 已有 Playwright 运行时（本轮安装 Chromium 151） |
| 队列/重试/断点 | crawlee-python（9.7k★） | 复用 `skillkit.policy` + checkpoint |

## 4. 建议的优先级

1. **P0（已完成）**：探测画像 + 三引擎抽取 + 兼容矩阵 + 登录态安全边界。
2. **P1（建议下一轮）**：把 `probe_site` 的判定接入 `material_crawler`，按 `render_layer` 自动选静态/浏览器路径。
3. **P2**：为 Bilibili 公开 API 增加专用适配器（详情/热门/字幕可用性探测）。
4. **P3**：Scrapling / Crawl4AI 仅在"反爬升级且现有路径失效"时做隔离试用，不默认引入。

## 5. ROI 说明

- 已落地部分零新增强制依赖（trafilatura 可选），复用既有 Playwright 与 `skillkit.http`，维护成本低。
- 真正的收益是**减少误判**：先探测再选型，避免对 SPA 空壳做无效解析、对需签名接口做无效重试。
