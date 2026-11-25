---
name: boss-auto-apply
description: BOSS 直聘实习岗自动投递执行器（07_bossauto）。通过 Chrome CDP 接管已登录的 boss-helper 扩展，按保号优先策略（每日 10 份、逐份间隔 5-10 分钟、拟人化操作）投递中厂/小厂实习岗，含封禁冷却闸门、风控急停、额度安全挂起与状态台账。用户要求自动投递、批量打招呼、查看今日投递额度或排查投递中断时使用。
version: 2.0.0
language: zh-CN
triggers: [BOSS自动投递, 自动打招呼, 批量投递实习, 今日投递额度, boss-helper, 投递中断, LIMIT_EXHAUSTED, 封禁冷却, 账号风控]
not_triggers: [普通岗位查询, 简历修改, 面试准备, 公司调研, 非BOSS平台投递, 浏览器插件安装]
executor: D:\00_skiill_ku\07_bossauto\run_scheduled.ps1 + bossctl.js
runtime: Chrome CDP 9222 + boss-helper 扩展（fpfjpeicdgddkojpldehpfnbnlojmbcb）
---

# BOSS 自动投递（07_bossauto）

> ## ⚠️ 最高风险警告：本模块直接关联真实账号
>
> **本模块直接关联真实账号，极易触发阿里风控。一旦触发，封禁是「账号级」的——换 IP、切换移动数据均无效（2026-11-24 已实测：切换移动数据后仍封禁至 22:52）。**
>
> **所有代码修改必须经过离线测试验证延迟逻辑，严禁盲目上线。**
> 离线测试至少覆盖：封禁闸门退出码、拟人化参数区间、逐份间隔、风控急停路径。
> 任何一次线上运行前，必须确认 `state.json` 的 `banned_until` 已过期且无人为风控信号。

> 本文件是**模型入口**；人类运维 Runbook 见 [README.md](./README.md)。
> 目录名保留 `07_bossauto`（历史路径），不要改名——Trae Schedule 任务
> 与 `run_scheduled.ps1` 都写死了该路径，改名会让定时任务静默失效。

## 0. 封禁冷却闸门（最高优先级）

`state.json` 顶层字段 `banned_until` 是**全局熔断开关**：

```json
{ "banned_until": "2026-11-24T22:52:00", "banned_note": "账号级封禁，解除后须人工确认" }
```

- 任何脚本（`bossctl.js` 任意子命令、`run_scheduled.ps1` 任意批次）启动第一件事就是比对该字段与当前时间。
- 命中时：打印 **`账号处于封禁冷却期，禁止运行`**，**不发起任何网络请求**，退出码 `8`。
- 冷却期结束后不会自动放开——确认账号恢复正常后，需人工把 `banned_until` 改成过去时间或删除该字段。
- 长间隔睡眠期间每分钟复查一次，若被人工写入新封禁立即退出。

## 1. 能力边界

**做什么：**

- 在用户已登录的 Chrome 上，通过 CDP（127.0.0.1:9222）接管 boss-helper 扩展。
- 按「保号优先」策略投递：**每日上限 10 份**、**每份强制间隔 5-10 分钟**、**每次操作前拟人化浏览 5-15 秒**。
- 校验简历图存在；招呼语由 boss-helper 扩展选项维护，脚本只读不覆盖。
- 统计真实产出（扩展 `today.success` 优先），写 `state.json` 与 `daily.log`。
- 遇到验证码 / 异常行为页 / 封禁页**立即截图并急停**，不刷新、不重试、不绕过。

**不做什么：**

- 不绕过验证码、登录验证、平台风控；遇到即停止。
- 不修改在线简历、不群发附件、不重复投同一 HR。
- 不投大厂批次。
- 不在封禁冷却期内运行；不读取/导出 Cookie、Token。

## 2. 拟人化参数（humanize.js）

| 维度 | 实现 | 参数 |
|---|---|---|
| 鼠标轨迹 | 三次贝塞尔曲线 + 随机控制点 + 缓入缓出 + 到位过冲回弹 | 14-26 步，步间 6-22ms |
| 点击前抖动 | 落点随机微调 2-4 次后按下 | ≥200ms，单次 60-110ms |
| 按键时长 | 按下到松开随机 | 65-145ms |
| 阅读停留 | 进入搜索/详情页后滚动浏览 JD | 5-15 秒，滚轮 120-420px/次 |
| 输入延迟 | 逐字 `Input.insertText` | 150-400ms/字，8% 概率 +400-1100ms 思考停顿 |
| 投递间隔 | 每投 1 份后强制等待 | 300-600 秒（5-10 分钟） |
| 启动时间 | 定时触发后随机延迟 | 0-45 分钟（9:05 → 9:05-9:50） |

> **技术说明**：本模块**不使用 Playwright**（会触发反爬空白页），全部拟人化在原生 CDP `Input` 域实现，效果等价于 `page.mouse.move()`。
> 扩展面板按钮在 shadowRoot 内，通过 `getBoundingClientRect` 取坐标后用真实鼠标事件点击，不使用 `element.click()`。

## 3. 输入契约

| 输入 | 位置 | 必填 | 说明 |
|---|---|---|---|
| 批次 | `run_scheduled.ps1 [-Batch morning] [-Manual]` | 否 | 默认 morning；`-Manual` 跳过随机延迟 |
| 额度配置 | `tiers.json` | 是 | `dailyTotal=10`、`humanize` 参数块 |
| 公司名单 | `companies.json` | 是 | `big` 名单；mid/small 统一「排除大厂」 |
| 简历图 | 扩展 IndexedDB | 是 | `sync` 只校验可读，不写入覆盖 |
| 招呼语 | boss-helper 扩展选项（用户自行设置） | 是 | 脚本只读不覆盖 |
| Chrome CDP | `http://127.0.0.1:9222/json/version` | 是 | 由 `ensure_chrome.ps1` 拉起；不可用退出码 3 |
| 封禁状态 | `state.json` → `banned_until` | 是 | 冷却期内一律 exit 8 |

## 4. 输出契约

| 产物 | 位置 | 内容 |
|---|---|---|
| 运行日志 | `daily.log` | DAILY/PLAN/RUN/RESULT/HUMAN_GAP/STOP/DONE |
| 调度日志 | `_logs\bossauto\run_<stamp>_<batch>.log` | 包装脚本全量输出 |
| 冷却日志 | `_logs\bossauto\cooldown.log` | 每次被闸门拦截的记录 |
| 急停证据 | `_logs\bossauto\EMERGENCY_<ts>.jpg/.json` | 风控页截图 + 现场信息 |
| 状态台账 | `state.json` | `banned_until`、每日 `applied`、`suspended` |

## 5. 执行链路

```
run_scheduled.ps1
  → STEP0 封禁冷却闸门（exit 8）
  → 周末跳过
  → 随机启动延迟 0-45min（-Manual 时跳过）
  → 延迟后复查封禁
  → ensure_chrome.ps1（CDP 9222，失败 exit 3）
  → bossctl.js sync（只读校验简历图，失败 exit 2）
  → bossctl.js daily 10
       → assertNotBanned（二次闸门）
       → 逐份循环（units = plan 展开，每份 cap=1）：
            风控抽检 → 打开搜索页 → 随机停顿 4.5-8.5s
            → 风控抽检 → 拟人化阅读滚动 5-15s
            → 风控抽检 → 贝塞尔鼠标点击「开始投递」
            → 运行态确认（暂停按钮出现，最多重试 3 次）
            → 轮询进度（每 15s 风控抽检）
            → 统计 delta（扩展 today.success 增量）
            → 落盘 state.json
            → 强制 HUMAN_GAP 5-10 分钟（每分钟复查封禁）
```

## 6. 停止与急停策略

| 情况 | 行为 | 退出/记录 |
|---|---|---|
| 封禁冷却期 | 不启动，不发请求 | exit 8，`cooldown.log` |
| CDP 未就绪 | 不启动投递 | exit 3 |
| 资产校验失败 | 不启动投递 | exit 2 |
| **验证码 / 异常行为页 / 封禁页** | **立即截图 + 急停，不刷新不重试** | exit 9，`EMERGENCY_*` |
| 连续两轮 delta=0 | 判定额度用尽/限流 | `LIMIT_EXHAUSTED`，安全挂起 |
| 扩展计数已达 limit | 正常结束 | `EXT_LIMIT_REACHED`，安全挂起 |
| 进度停滞 ~30s | 拟人化点击「暂停」后结束本页 | — |
| shadowRoot 连续 3 次消失 | 跳出 | `PANEL_GONE x3` |

## 7. 常用命令

```powershell
$DIR = "D:\00_skiill_ku\07_bossauto"

# 手动跑（跳过随机延迟）
powershell -ExecutionPolicy Bypass -File "$DIR\run_scheduled.ps1" -Manual

# 只算今日计划（封禁期会被闸门拦截）
node "$DIR\bossctl.js" plan

# 只读资产校验
node "$DIR\bossctl.js" sync

# 查看扩展配置 / 今日计数
node "$DIR\bossctl.js" extread
node "$DIR\bossctl.js" counttoday
```

## 8. 离线测试（线上运行前必做）

```powershell
node --test D:\00_skiill_ku\07_bossauto\tests\test_pipeline.js
```

覆盖：配额分配、计划生成、星期额度、三重额度约束、搜索 URL 编码、资产闸门、
deliveryLimit 计算、额度用尽文案、挂起状态写入、离线端到端链路。

**拟人化逻辑必须离线验证，不得靠线上试跑：**

```powershell
# 纯函数验证：贝塞尔轨迹点数量、区间、单调性
node -e "const {Human}=require('D:/00_skiill_ku/07_bossauto/humanize.js'); console.log('loaded')"

# 封禁闸门验证（应输出拒绝并 exit 8）
node D:\00_skiill_ku\07_bossauto\bossctl.js plan
echo $LASTEXITCODE
```

## 9. 已知局限（必须如实告知用户）

- **账号级封禁不可绕**：换 IP / 移动数据无效；唯一有效手段是降低频率与行为异常度。
- 扩展内部点击由插件完成，脚本无法对每一次岗位点击注入拟人化；因此用「每次只投 1 份 + 长间隔 + 投前阅读」降低整体频率特征。
- 扩展 `deliveryLimit` 语义是「今日已投总量上限」，脚本按 `扩展计数 + 1` 设置。
- 扩展计数有 1-2 分钟延迟；产出以 `today.success` 增量为准。
- 掉登录 / 验证码 / 页面改版都会中断；无人值守时记 BLOCKED，需人工处理。
- 定时任务由 Trae Schedule 触发，客户端离线则当日不执行。
- **任何频率上调都必须先经过至少一周无风控观察，且由用户明确批准。**
