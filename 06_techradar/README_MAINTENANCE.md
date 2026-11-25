# TechRadar 维护手册（README_MAINTENANCE）

> 适用目录：`D:\00_skiill_ku\06_techradar`
> 更新：2026-11-24 | 覆盖：计划任务、浏览器会话、Folo/Reddit 采集、故障排查、安全

## 1. 系统组成

```
collect_public_suite.py   公开源（HN/GitHub/arXiv/RSS/安全源/聚合源）
collect_folo.py           Folo：令牌优先，缺令牌时走浏览器登录态
collect_reddit.py         Reddit：OAuth2 优先，缺凭据时走浏览器登录态（JSON→DOM 回退）
fetch_bodies.py           正文回源补抓
lifecycle_run.py          daily/weekly/monthly/quarterly 生命周期
websession.py             浏览器会话：拉起/复用/残留清理/自动关闭
proxy_env.py              本机代理探测（3067 等），供 HttpClient / Chrome 使用
```

数据落库：`data/techradar.db`（SQLite）。运行台账：`job_runs`。报告：`D:\00_skiill_ku\_reports\lifecycle\`。
完整脚本清单（23 个）与参数见 [SKILL.md §4.5](./SKILL.md) 和 [CLI_REFERENCE.md](./CLI_REFERENCE.md)。

## 2. 计划任务

任务名：`TechRadar_Daily`，每天 07:30，调用 `scripts\tasks\daily.cmd`。

当前设置（已修复）：

| 项 | 值 | 说明 |
|---|---|---|
| StartWhenAvailable | True | 错过计划后尽快补跑 |
| DisallowStartIfOnBatteries | False | 电池供电也允许启动 |
| StopIfGoingOnBatteries | False | 切电池不中断 |
| WakeToRun | True | 唤醒计算机执行 |
| 运行身份 | 26808 / InteractiveToken / Limited | 需用户登录会话 |

**已知限制**：改为 `SYSTEM` 或 S4U（无论是否登录都运行）需要管理员权限；
在普通权限下 `Register-ScheduledTask` 返回 `Access is denied (0x80070005)`。
如需切换，请在**管理员 PowerShell** 执行：

```powershell
$t = Get-ScheduledTask -TaskName 'TechRadar_Daily'
$p = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Set-ScheduledTask -TaskName 'TechRadar_Daily' -Principal $p
```

切换后浏览器将以 session 0 运行，建议同时设置 `TECH_RADAR_BROWSER_MODE=headless`
（注意：headless 更容易被 Reddit 识别并 403，见第 4 节）。

## 3. 浏览器会话（websession.py）

- 调试端口：**9333**（`TECH_RADAR_CDP_PORT` / `TECH_RADAR_CDP` 可改）。
- 配置目录：`D:\00_skiill_ku\_browser_profile`（由默认 Chrome 的 `Local State + Cookies` 复制而来，
  因为 Chrome 136+ 禁止对默认目录开启远程调试）。
- 启动模式：`TECH_RADAR_BROWSER_MODE=offscreen`（默认，窗口移到 -32000,-32000）或 `headless`。
- 自动管理：
  - 端口不通 → 先按 `*_browser_profile*` 匹配并杀掉残留 Chrome → 重新拉起；
  - 只杀本项目配置目录的 Chrome，**不会动用户日常 Chrome**；
  - 采集结束（且浏览器是本进程拉起的）→ `taskkill /T /F` 并删除 `data/browser_session.json`；
  - 若 9333 已在运行（复用模式），采集后不会关闭它。
- 登录态刷新：`scripts\tasks\refresh_browser_profile.ps1`（会关闭 Chrome，请在非采集时段执行）。
- 代理：启动时自动调用 `proxy_env.detect_proxy()`，有可用本机代理则注入 `--proxy-server`。
- 测试/CI：设 `TECH_RADAR_DISABLE_BROWSER=1` 可禁用浏览器回退，认证源按 `BLOCKED/AUTH_REQUIRED` 处理（不启动 Chrome）。

## 4. 采集通道与限制

| 通道 | 方式 | 现状 | 备注 |
|---|---|---|---|
| Folo | CDP 浏览器登录态 → `api.folo.is` 同源接口 | READY | 20 条已入库；无令牌亦可 |
| Reddit JSON | `/r/<sub>/new.json` | 403 | 数据中心 IP 被风控 |
| Reddit DOM | 真实浏览器打开 `/r/<sub>/new/`，读 `shreddit-post` | READY（offscreen） | 40 条已入库；8–15 秒间隔 |
| Reddit RSS | `/r/<sub>/.rss` | 404 | Reddit 已下线该 RSS |
| curl_cffi | impersonate=chrome | 直连超时 / 代理 403 | TLS 指纹不是瓶颈，IP 才是 |

**重要**：Reddit 的 `--headless=new` 会被识别为自动化并返回 403；`offscreen` 模式正常。
因此默认旷用 offscreen。

## 5. 故障排查

| 现象 | 排查 | 处理 |
|---|---|---|
| 任务 `Last Result=0x800710E0` | 电池/会话被拒 | 已修：电源策略全关；确认用户已登录 |
| Folo/Reddit 报 `导航失败/Timeout` | 9333 是否存活、代理是否可用 | 重跑；`websession` 会自动清理残留并重启 |
| Folo `AUTH_REQUIRED` | Cookie 过期 | 运行 `refresh_browser_profile.ps1` |
| Reddit 403 | 出口 IP 被风控 | 换代理出口，或走官方 OAuth2（见下） |
| `Access is denied` 改任务 | 非管理员 | 用管理员 PowerShell 执行第 2 节命令 |

## 6. OAuth2 预留接口

`collect_reddit.py` 已支持用户上下文令牌：

```
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_REFRESH_TOKEN=...   # 有则走 grant_type=refresh_token
```

无凭据时保持 BLOCKED，不影响其它通道。正式接入前需完成 Reddit app-registration 审批。

## 7. 安全

- `.gitignore` 已忽略：`_browser_profile/`、`cookies_*.db`、`06_techradar/data/browser_session.json`、`.env`、`*.db`。
- Cookie / token 只在本机内存与 `.env` 中使用，不写入日志、数据库、报告。
- 所有删除/清理操作默认 dry-run；`lifecycle_config.json` 的 `apply_purge=false` 时永不真删。

## 8. 常用命令

```powershell
# 手动跑每日采集（dry-run，不删数据）
D:\00_skiill_ku\.venv\Scripts\python.exe D:\00_skiill_ku\06_techradar\scripts\lifecycle_run.py --job daily

# 单独采集
D:\00_skiill_ku\.venv\Scripts\python.exe D:\00_skiill_ku\06_techradar\scripts\collect_folo.py --limit 20
D:\00_skiill_ku\.venv\Scripts\python.exe D:\00_skiill_ku\06_techradar\scripts\collect_reddit.py --limit 25

# 检索
D:\00_skiill_ku\.venv\Scripts\python.exe D:\00_skiill_ku\06_techradar\scripts\radar_query.py --db D:\00_skiill_ku\06_techradar\data\techradar.db --text "关键词" --limit 5
```

## 9. 排障型情报（v2，2026-11-24）

新增来源：

| 来源 | 脚本 | 说明 |
|---|---|---|
| knowledge_base | `import_knowledge.py` | 实战复盘知识（4 条：headless/offscreen、curl_cffi、Reddit DOM、schtasks S4U） |
| reddit_tech | `collect_reddit_topics.py` | r/webscraping、r/Python，复用浏览器登录态，8–15 秒间隔 |
| github_issues | `collect_github_issues.py` | GitHub Issues 搜索（未认证 10 次/分钟，可选 GITHUB_TOKEN） |
| stackoverflow | `collect_stackoverflow.py` | StackExchange API（playwright、python-requests） |

标签：`anti-bot`、`troubleshooting`、`code-snippet`、`windows-permission`（`tagging.py`，daily 自动补标）。

代码块权重：`snippets.py` 抽取 `<pre><code>` / 围栏代码，`fetch_bodies.py` 追加进正文，FTS 可检索。

检索示例：

```powershell
# 技术意图自动优先知识库/Issues/SO
python radar_query.py --db ...\techradar.db --text "windows 计划任务 SYSTEM 权限" --limit 5
python radar_query.py --db ...\techradar.db --text "playwright 403 bypass" --intent tech
python radar_query.py --db ...\techradar.db --tag windows-permission --limit 5
```
