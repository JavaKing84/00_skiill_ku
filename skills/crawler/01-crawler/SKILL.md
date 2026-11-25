---
name: 01-crawler
description: 网站数据采集协议库（P0-P5 执行协议 + 反爬排障 + 实际下载执行器）。当用户要求抓取网站数据、采集正文/列表/表格、批量下载网页资源、自动翻页、提取 API/XHR、编写或排查 Playwright/Camoufox 爬虫、分析 403/429/验证码、登录态采集、断点续采与去重、寻找并下载图片视频素材时触发。
version: 1.0.0
triggers: [抓取, 采集, 爬取, 爬虫, 批量下载, 翻页, 反爬, 403, 429, 验证码, XHR, 签名参数, 登录态, 断点续采, 去重, 找素材]
not_triggers: [打开网页, 阅读单篇文章, 总结已有文章, 普通搜索, 网页技术概念解释, 视频剪辑, 技术选型与趋势研究]
entry: ../../../01_crawler/SKILL.md
scripts_dir: ../../../01_crawler/scripts
executor: ../../../03_video/material-sourcing-crawler/scripts/material_crawler.py
---

# 01-crawler

协议库负责“怎么做、怎么定性、怎么排障”，执行器负责“真的下载、真的落盘”。

## 路径映射

| 能力 | 实际路径 |
|---|---|
| 协议库（canonical） | `../../../01_crawler/SKILL.md` |
| 采集执行器 | `../../../03_video/material-sourcing-crawler/scripts/material_crawler.py` |
| 浏览器内核 | `../../../01_crawler/runtime`（Playwright / Camoufox） |
| 收藏仓库参考 | `../../../01_crawler/repos`（第三方克隆，不入库） |

## API 优先原则

遇到公开数据源（新闻、热搜、榜单、天气、金价等），**优先调用 API，而不是用浏览器渲染抓取**。
参考 `skills/data/60s-api` 的封装方式（`requests` + 超时 + 重试 + 字段裁剪）。

```bash
# 示例：每日 60 秒新闻
python skills/data/60s-api/scripts/fetch.py --endpoint 60s
```

## 硬约束

- 遵守 robots、服务条款与访问频率（建议翻页间隔 4-7 秒）。
- 不绕过登录授权、付费墙、验证码、访问控制；遇到即停止并报告。
- 不打印 Token / Cookie / API Key，日志必须脱敏。
- 采集产物必须落盘并校验（SHA256 / 大小 / ffprobe），不得只交付远端 URL。
- 缺少执行工具或授权时如实报告阻塞，不得用方案冒充结果。
