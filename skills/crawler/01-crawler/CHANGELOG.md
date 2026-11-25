# CHANGELOG — 01-crawler

## 1.0.0 — 2026-11-25

- 新建标准聚合入口，遵循 SKILL.md frontmatter 规范。
- 相对路径映射到 `01_crawler/`（协议库）与 `03_video/material-sourcing-crawler/scripts/material_crawler.py`（执行器）。
- 新增「API 优先原则」：公开数据源优先走 `skills/data/60s-api`，避免无谓的浏览器渲染抓取。
- 同步在 `01_crawler/SKILL.md` 正文顶部加入 API 优先指导。
