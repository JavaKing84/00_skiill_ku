# 新技术采纳评估（Phase 3 / 4）

- 时间：2026-11-18 01:45
- 数据来源：GitHub 官方 API（`_reports/probes/github_candidates.json`）+ 隔离 venv 实测（`_reports/probes/extract_bench.json`）

## 1. 候选项目真实性（API 实测，非热度传闻）

| 项目 | Stars | 最近推送 | 归档 | 许可证 | 语言 | 结论 |
|---|---|---|---|---|---|---|
| D4Vinci/Scrapling | 103,899 | 2026-11-17 | 否 | BSD-3-Clause | Python | 暂缓（体量大，与 Playwright 重叠） |
| unclecode/crawl4ai | 87,474 | 2026-11-17 | 否 | Apache-2.0 | Python | 暂缓（依赖重，需 LLM 抽取场景再引入） |
| microsoft/playwright-python | 15,116 | 2026-11-17 | 否 | Apache-2.0 | Python | 已在用（本轮安装 Chromium 151） |
| browser-use/browser-use | 121,303 | 2026-11-17 | 否 | MIT | Python | 暂缓（Agent 编排，超出采集层） |
| apify/crawlee-python | 9,677 | 2026-11-17 | 否 | Apache-2.0 | Python | 参考（借鉴队列/重试模型） |
| firecrawl/firecrawl | 202,568 | 2026-11-17 | 否 | **AGPL-3.0** | TypeScript | 不引入（许可证与服务化冲突） |
| ScrapeGraphAI/Scrapegraph-ai | 32,833 | 2026-10-06 | 否 | MIT | Python | 暂缓（LLM 依赖） |
| adbar/trafilatura | 7,146 | 2026-11-17 | 否 | Apache-2.0 | Python | **采纳（可选依赖）** |
| MagicalMirror（搜索 Top） | **1** | 2020-01-31 | 否 | Apache-2.0 | - | **拒绝**（停更 6 年） |

## 2. 隔离环境实测（`%TEMP%\crawl_lab`，未污染主环境）

安装：`trafilatura 2.3.1` + `readability-lxml`，仅在该 venv 内。

| 页面 | trafilatura | readability | 内置兜底 |
|---|---|---|---|
| Wikipedia / Web_scraping | 26,293 字符 | 8,731 | 31,539（含导航噪音） |
| HuggingFace Blog / llama2 | 11,331 | 11,598 | 15,458（含页脚噪音） |
| GitHub Blog / Engineering | 3,113 | **238（失效）** | 14,518（噪音多） |

判定：
- **trafilatura 为默认引擎**（最干净，三个站点均有效）。
- readability 作为降级（个别站点失效，不能单独依赖）。
- 内置兜底保证"零依赖也能出正文"，但噪音大，只用于最后兜底。

## 3. 采纳策略

| 层 | 方案 | 依赖 |
|---|---|---|
| 默认 | 内置兜底（零依赖） | 无 |
| 推荐 | trafilatura（可选安装） | `pip install trafilatura` |
| 降级 | readability-lxml | 可选 |
| 浏览器 | 既有 Playwright 运行时 | 已有 |
| 不引入 | firecrawl / Scrapling / crawl4ai / browser-use | — |

## 4. 兼容与回滚

- 所有可选依赖均为**运行时 try-import**，缺失不影响主流程。
- 回滚：删除 `01_crawler/scripts/{probe_site,probe_logged_in,extract_article,build_platform_matrix}.py` 与 `reports/` 即可，不影响既有采集器。
- 许可证：采纳项均为 Apache-2.0/BSD，无 AGPL 传染风险。
