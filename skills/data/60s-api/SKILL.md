---
name: 60s-api
description: 60s 高质量公开 API 数据源封装（每日60秒新闻、B站/微博/知乎/抖音/百度/头条热搜、天气、农历、Epic 免费游戏、翻译）。当用户要求获取每日新闻、热搜榜单、实时天气、金价油价类资讯、翻译或做每日简报时触发，应优先调用本 API 而不是用浏览器抓取网页。
version: 1.0.0
triggers: [每日新闻, 60秒读世界, 今日新闻, 热搜, 热榜, B站热搜, 微博热搜, 知乎热榜, 抖音热搜, 百度热搜, 头条, 实时天气, 农历, 免费游戏, 翻译]
not_triggers: [需要登录才能访问的数据, 站内私域数据采集, 视频剪辑, 代码报错修复, 需要浏览器渲染的动态页面]
entry: ../../../01_crawler/SKILL.md
scripts_dir: ./scripts
---

# 60s-api

把「公开资讯类数据」从浏览器抓取改为 API 直取，降低反爬风险和耗时。

## 快速使用（在库根目录执行）

```bash
# 列出可用接口
python skills/data/60s-api/scripts/fetch.py --list

# 每日 60 秒新闻
python skills/data/60s-api/scripts/fetch.py --endpoint 60s

# 热搜 Top 10
python skills/data/60s-api/scripts/fetch.py --endpoint bili --limit 10

# 翻译
python skills/data/60s-api/scripts/fetch.py --endpoint fanyi --param text=hello

# 只要原始响应前 100 字符（连通性自检）
python skills/data/60s-api/scripts/fetch.py --path /v2/60s --head 100
```

## 实例与可用性（2026-11-25 实测）

| 域名 | 状态 | 说明 |
|---|---|---|
| `https://60s.viki.moe` | ❌ SSL 不通 | 官方主域名，本机网络被墙/限流，仍保留为首选 |
| `https://api.elysiayanyu.top` | ✅ 200 | 社区公共实例，自动回退命中 |
| `https://60s.mizhoubaobei.top` | ✅ 200 | 社区公共实例 |
| `https://60s.okbaike.com` | ✅ 200 | 社区公共实例 |
| `https://60s.7se.cn` | ⚠️ 字段不兼容 | 魔改版「每天100秒」，schema 不同，未纳入默认链路 |

脚本按 `HOSTS` 顺序自动回退；也可用环境变量 `SIXTY_S_API_BASE` 指定自建实例。

## 已实测可用的接口

| 名称 | 路径 | 返回 |
|---|---|---|
| 60s | `/v2/60s` | 每日 60 秒新闻（`data.news[]`） |
| bili | `/v2/bili` | B 站热搜列表 |
| weibo | `/v2/weibo` | 微博热搜列表 |
| zhihu | `/v2/zhihu` | 知乎热榜 |
| douyin | `/v2/douyin` | 抖音热搜 |
| baidu | `/v2/baidu/hot` | 百度热搜 |
| toutiao | `/v2/toutiao` | 今日头条 |
| weather | `/v2/weather` | 实时天气（支持 `city` 参数） |
| lunar | `/v2/lunar` | 农历与节假日 |
| epic | `/v2/epic` | Epic 免费游戏 |
| fanyi | `/v2/fanyi` | 翻译（需 `text` 参数） |

> `/v2/gold`、`/v2/hot`、`/v2/itnews`、`/v2/oil`、`/v2/history` 在公共实例上实测 404，
> 未纳入封装；需要时先确认目标实例是否实现，再扩展 `ENDPOINTS`。

## 错误处理约定

- 单实例失败自动重试 1 次并切换下一实例；全部失败返回 `BLOCKED:` 与逐实例原因，退出码 2。
- 超时默认 10 秒，可用 `--timeout` 调整。
- 仅依赖 `requests`，不引入额外 SDK。
- 不缓存、不落库；需要沉淀请交给 `06_techradar` 入库流程。
