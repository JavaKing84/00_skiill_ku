# BOSS 自动投递 Runbook

> 模型入口见 [SKILL.md](./SKILL.md)（输入/输出/重试/额度策略）；本文件是人类运维手册。

## 目的
每个工作日用 boss-helper 插件投递实习岗位，只投**中厂+小厂**（不投大厂批次），岗位方向：Python / Go / 后端 / Web 开发 / AI 全栈 / AI 应用 / 软件开发实习。

**2026-11-24 账号级封禁后改为「保号优先」策略：每日上限 10 份，每份强制间隔 5-10 分钟，投前拟人化浏览 5-15 秒，启动时间随机延迟 0-45 分钟。**

## ⚠️ 封禁冷却闸门（最高优先级）
`state.json` 顶层 `banned_until` 为全局熔断：
- 任何脚本启动先比对当前时间，命中即打印「账号处于封禁冷却期，禁止运行」并以退出码 8 结束，**不发任何网络请求**
- 冷却结束不会自动放开，需人工确认账号恢复后手动清除该字段
- 2026-11-24 实测：封禁为**账号级**，切换移动数据无效；起因是 19:44-20:15 两脚本并发操作同一聊天页 + 分钟级数十次会话切换 + 批量发图

## 目录
- `ensure_chrome.ps1`：确保 Chrome 带 CDP（9222）启动
- `guard.js`：封禁冷却闸门 + 风控页判定 + 急停截图
- `humanize.js`：CDP 拟人化原语（贝塞尔鼠标、阅读停留、逐字输入、点击抖动）
- `bossctl.js`：主控（extread / counttoday / tier / panel / plan / sync / smoke / daily [cap]）
- `run_scheduled.ps1`：定时调度包装（`-Batch morning` `-Manual`），含封禁闸门、随机启动延迟与资产校验
- `tiers.json`：每日额度（10）、搜索词权重、中厂/小厂配额、`humanize` 拟人化参数
- `companies.json`：大厂/中厂名单（small = 排除大+中的全部）
- `state.json`：封禁状态 `banned_until` + 每日已投数量
- `daily.log`：执行日志；`D:\00_skiill_ku\_logs\bossauto\`：调度包装运行日志

## 定时任务（Trae Schedule，工作日触发）
| 任务 | 时间 | 批次 | 额度 |
|---|---|---|---|
| Boss投递-早间 | 周一~五 09:05 | morning | 10（全天唯一一次） |

- 单日只跑一次：09:05 触发后脚本内部随机延迟 0-45 分钟，实际落在 09:05–09:50
- 每份之间强制 5-10 分钟，10 份需要 50–100 分钟，全天窗口约 09:05–11:30
- 周末 0 份；下午/晚间不再触发（原 14:35、19:05 两个任务已删除）
- 当日已投满时再次触发会直接 `DAILY_QUOTA_REACHED` 挂起，不发请求

## 每次执行步骤（手动运行时）
1. `powershell -ExecutionPolicy Bypass -File D:\00_skiill_ku\07_bossauto\run_scheduled.ps1 -Manual`
   - 自动：封禁闸门 → ensure_chrome → sync 资产校验（imgOk=true）→ `node bossctl.js daily 10`
   - `-Manual` 跳过随机启动延迟；不加则随机等 0-45 分钟
2. 校验失败退出码 2（资产）、3（CDP）；任一不符先修复再继续，无法修复中止并写日志
3. 读取 `state.json` 与 `daily.log` 记录：当日新增、各阶段数量、失败原因

## 固定规则
- **招呼语完全由 boss-helper 扩展选项维护**；`bossctl.js sync` 只读校验简历图是否存在，**不写入、不覆盖、不校验文案**
- 每日上限 **10 份**；每份之间强制 5-10 分钟；投前拟人化阅读 5-15 秒
- **封禁冷却期内禁止一切自动化请求**（`state.json` → `banned_until`，退出码 8）
- **遇到验证码 / 异常行为页 / 封禁页：立即截图 + 急停（退出码 9），不刷新、不重试、不绕过**
- 搜索词保证含「实习」；BOSS URL 固定 `experience=108`（在校生）+ `jobType=1902`（实习）；jobTitle 用排除模式，只排除算法 / Java / C/C++，不再用「含实习」包含过滤
- 不修改在线简历；不向已有 HR 群发附件简历；同一 HR 不重复投递（sameHrFilter）
- 产出统计以扩展 `today.success` 增量为主，聊天列表时间戳（countSince）仅作回退

## 简历图片补发（11/24 踩坑记录）
- **图片必须压缩**：原图 `assets/resume.png`（1.2MB / 1785×2526）经 CDP 注入后上传永久卡 loading，无法送达；压缩为 `assets/resume_small.jpg`（284KB / 1000×1415）后 4 秒内送达
- 发送三步缺一不可：`DOM.setFileInputFiles` 到 `.btn-sendimg input[type=file]` → 等预览出现 → **CDP 真实鼠标事件**（`Input.dispatchMouseEvent`）点击 `.btn-v2.btn-sure-v2.btn-send`；`element.click()` 无效
- 成功判据：聊天区出现 `img.message-image`（原图 1785×2526 / 压缩图 1000×1415）且 loading 归零、气泡下显示「送达」
- 会话列表的 `[图片]` 标记**不可作为判据**（PK 卡片图标也会触发），必须进会话读 DOM
- **禁止并发操作同一聊天页**：两个脚本同时点会话/发图会导致列表错位、重复发送；执行前先确认无其他 node 进程

## 已知局限与风险
- **投递过滤配置（11/25 更新）**：mid/small 统一「排除大厂名单」（include:false）；岗位名「含实习」包含过滤已关闭，改为 **排除模式**（算法、机器学习、深度学习、计算机视觉、NLP、Java开发/后端、C++、C/C++、C语言、C#）；工作内容排除 Java / C/C++ / C# 关键词；BOSS URL 固定 `experience=108`（在校生）+ `jobType=1902`（实习），只投 Python / Go / AI 全栈 / 后端方向。副作用：JD 中提及 Java/C++ 的 Python 岗可能被误伤
- **扩展 deliveryLimit 语义（11/24 实测修正）**：扩展把 deliveryLimit 当「今日已投总量上限」而非本批额度；必须设为 used+appliedTotal+capNow，设成本批 cap 会因"今日已投>cap"拒绝启动（progress=null 根因之一）
- **SPA 死按钮（11/24 实测修正）**：navigate 刷新后立即点「开始投递」可能落在未重绑事件的按钮上（点击 CLICKED 但扩展不启动）；runPage 已加启动确认（4s×3 次查「暂停」按钮），未启动则重试点击，3 次失败记 NOT_STARTED 跳页
- **runPage/statOf null 保护（11/24 实测修正）**：页面异常时裸读 shadowRoot 会 TypeError 炸整个 daily（JS_ERR FATAL）；已加保护 + PANEL_GONE x3 跳出；countSince 失败降级为 delta=0 走防空转
- **扩展面板文本不可读**：shadowRoot innerText 为空（嵌套 shadow DOM），progress/今日投递数字拿不到；运行态判定以「暂停按钮存在」为准，产出以聊天列表 countSince 与 extread today.success 对账
- **登录态**：11/23 04:13 曾全页跳 `/passport/zp/verify.html code=36` 安全验证；11/24 18:25 掉登录（/web/user/ 扫码页）；定时任务无人值守时遇验证码/掉登录只能记 BLOCKED，需人工开 Chrome 处理
- **反爬**：CDP 打开 BOSS 页面正常；不要用 Playwright 连接（会触发反爬空白页）
- **Trae 在线要求**：定时任务由 Trae Schedule 触发，Trae 客户端需开机在线；客户端未开则当日批次不执行
- 扩展 `web-geek-job-Today` 记录可能停在上一次日期，不能当作准数（tasks warn 计数为当日跨轮次累计，不按轮次重置）
- 扩展 deliveryLimit 在部分情况下不生效，脚本用聊天列表时间戳统计实际新增；聊天列表更新有延迟（实测 delta 统计滞后扩展 success 约 1-2 分钟）
