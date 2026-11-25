# 基线兼容性测试报告（Phase 2）

- 时间：2026-11-18 01:40
- 方法：`01_crawler/scripts/probe_site.py` 单次 GET + HTML 特征判定；登录态用 `probe_logged_in.py`（用户授权、只判定、不导出凭据）
- 原始产物：`_reports/probes/*.json`；汇总：`reports/platform_matrix.json` / `.md`

## 1. 公开通道结果

| 平台 | HTTP | 渲染层 | 结构化数据 | 公开 API | 结论 | 可实现的采集路径 |
|---|---|---|---|---|---|---|
| Bilibili 首页 | 200 | unknown（含内嵌 JSON） | 无 | `x/web-interface/popular` code=0 | **OK** | 公开 API 取热门/详情；字幕需登录态 |
| Bilibili API | 200 | - | - | JSON 正常 | **OK** | 直接 JSON 解析 |
| Douyin 首页 | 200 | unknown（JS 壳） | 无 | 热榜接口返回非 JSON | **PARTIAL** | 仅页面可访问；接口需签名 |
| Douyin 热榜 API | 200 | - | - | 非 JSON（风控/签名） | **BLOCKED** | 不逆向签名；仅能取页面可见内容 |
| 小红书 explore | 200 | `spa-shell` | `__INITIAL_STATE__` | 无公开 API | **PARTIAL** | 需 Playwright 渲染后解析内嵌状态 |
| YouTube 首页 | 200 | `ssr` | 无 | oEmbed 可用（未在本次探测） | **OK** | 页面 SSR + oEmbed |
| Wikipedia | 200 | `ssr` | JSON-LD | - | **OK** | 正文抽取基准站 |
| Reddit JSON | 403 | - | - | 需 OAuth | **BLOCKED** | 必须官方授权 |

## 2. 登录态通道结果（用户授权范围）

| 平台 | 判定 | 说明 |
|---|---|---|
| Bilibili | `LOGGED_OUT` | 页面正常，未检测到登录态；可匿名浏览 |
| Douyin | `BLOCKED_CHALLENGE` | 检测到验证/风控页，**已停止，未尝试绕过** |
| 小红书 | `BLOCKED_CHALLENGE` | 同上 |

结论：当前 `E:\Trae_Video_Workspace\browser_profile` **不具备可用的登录态**（或会话已失效）。
需要在浏览器中手动完成登录后重试；Agent 不代用户登录、不处理验证码。

## 3. 最小合规采集管线（已验证）

```
probe（判定渲染层与阻断）
  → 静态可读（SSR/JSON）: HttpClient → extract_article（trafilatura/readability/builtin）
  → SPA: Playwright（用户本机运行时）→ 渲染后取 DOM/内嵌状态
  → 需登录: 只用用户已登录会话；遇验证码即停
  → 需签名接口: 不逆向；改为页面可见数据或官方接口
  → 入库前 provenance 校验（URL + origin）→ SQLite → FTS5
```

## 4. 诚实标记

- `PARTIAL`：页面可访问但结构化数据需渲染/签名，未完成端到端采集。
- `BLOCKED`：风控/授权硬阻碍，不做任何绕过。
- `NOT_TESTED`：YouTube 播放地址解析、B 站字幕、小红书渲染后字段，本轮未做。
