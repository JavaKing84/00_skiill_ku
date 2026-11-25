# CHANGELOG — 60s-api

## 1.0.0 — 2026-11-25

- 新建技能：封装 60s 公开 API（每日 60 秒新闻、热搜榜单、天气、农历、Epic、翻译）。
- `scripts/fetch.py`：仅依赖 requests，10 秒超时、单实例重试 1 次、多实例自动回退。
- 实测记录：
  - `https://60s.viki.moe` 本机 SSL 不通（官方主域名，保留为首选）；
  - `https://api.elysiayanyu.top`、`https://60s.mizhoubaobei.top`、`https://60s.okbaike.com` 返回 200；
  - 11 个接口路径经实测可用；`/v2/gold`、`/v2/hot`、`/v2/itnews`、`/v2/oil`、`/v2/history` 在公共实例上 404，未纳入封装。
- 支持 `SIXTY_S_API_BASE` 环境变量指定自建实例。
