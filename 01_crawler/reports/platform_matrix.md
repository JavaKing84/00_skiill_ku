# 平台兼容性矩阵（实测）

生成时间：2026-11-18T01:44:03

> 说明：本表只记录单次公开探测事实；`spa-shell` 表示需要 JS 渲染；
> `blocked` 表示触发风控/验证，**不尝试绕过**；登录态仅判定页面可见状态。

| 平台 | 类型 | HTTP | 可达 | 渲染层 | 结构化数据 | 媒体线索 | 登录态 | 结论 |
|---|---|---|---|---|---|---|---|---|
| bilibili | page | 200 | 是 | unknown | 无 | 无 | - | OK |
| bilibili | api | 200 | 是 | - | - | - | - | OK |
| douyin | page | 200 | 是 | unknown | 无 | 无 | - | OK |
| douyin | api | 200 | 是 | - | - | - | - | BLOCKED(non_json：可能需签名/风控) |
| bilibili | logged_in | 200 | 否 | - | - | - | LOGGED_OUT | LOGGED_OUT |
| douyin | logged_in | 200 | 否 | - | - | - | BLOCKED_CHALLENGE | BLOCKED_CHALLENGE |
| xiaohongshu | logged_in | 200 | 否 | - | - | - | BLOCKED_CHALLENGE | BLOCKED_CHALLENGE |
| reddit | api | 403 | 否 | - | - | - | - | BLOCKED(auth) |
| generic_article | page | 200 | 是 | ssr | 有 | 无 | - | OK |
| xiaohongshu | page | 200 | 是 | spa-shell | 有 | 无 | - | PARTIAL(需 JS 渲染) |
| youtube | page | 200 | 是 | ssr | 无 | 无 | - | OK |

## 登录态探测（用户授权范围）

| 平台 | 结论 | 说明 |
|---|---|---|
| bilibili | LOGGED_OUT | 仅做页面可见状态判定 |
| douyin | BLOCKED_CHALLENGE | 检测到验证/风控，已停止 |
| xiaohongshu | BLOCKED_CHALLENGE | 检测到验证/风控，已停止 |
