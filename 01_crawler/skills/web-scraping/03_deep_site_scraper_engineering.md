---
id: WS-03
title: 单站点深度采集的工程化范式
level: 系统
phase: [P4]
triggers: [长期跑, 多任务, 要熔断, 要轮换, 账号池, 登录态, 定时监控, 要通知]
read_when: 目标需要 7x24 稳定运行、有登录态、有风控、要 AI 二次判定
skip_when: 一次性抓取；或目标是多源低频聚合（WS-04）
outputs: [五层项目骨架, FailureGuard, RotationPool, 拟人节奏表, 三重去重]
next: [WS-06]
---

# 🛠️ Skill 03: 单站点深度采集的工程化范式

> 拆解对象：[Usagi-org/ai-goofish-monitor](https://github.com/Usagi-org/ai-goofish-monitor)（闲鱼多任务实时监控系统，Playwright + AI + Web UI）
> 一句话结论：**它把"爬虫脚本"做成了"爬虫系统"** —— 风控识别、熔断、轮换、存储、调度、通知、AI 判定全部独立成层。这套骨架可以整体搬到任何需要长期稳定运行的采集项目上。
> **所属阶段**：P4 工程化（路线 A） ｜ 前置：P3 打通 ｜ 后续：WS-06

## 🎯 适用场景

- 目标站点有登录态、有风控、需要**7×24 长期跑**（而不是跑一次拿一份数据）
- 需要多任务/多关键词并发，每个任务独立配置
- 采集结果需要**AI 二次判定**（值不值得买 / 是不是目标客户 / 有没有风险）
- 单机部署、想给非技术用户一个 Web 界面

不适用：一次性批量抓取、纯 API 型站点（那种看 [04](./04_aggregator_pipeline_design.md)）。

---

## 一、分层架构（先把骨架立住）

```
src/
├── app.py            FastAPI 入口：挂路由、建库、起调度
├── api/              HTTP 接口层（tasks / accounts / results / settings）
├── core/             领域核心逻辑
├── domain/           数据模型与规则
├── infrastructure/   外部依赖（AI client、数据库、通知渠道）
├── services/         业务服务（调度、结果存储、价格历史、账号运行时）
├── scraper.py        采集器（Playwright）
├── rotation.py       账号 / 代理轮换池
├── failure_guard.py  任务级熔断器
├── keyword_rule_engine.py  关键词规则判定
├── ai_handler.py     AI 调用与图片分析
├── prompt_utils.py   生成"分析标准"的 meta-prompt
└── parsers.py        响应解析
```

**过人之处**：它没有把采集逻辑塞进 FastAPI 路由里，而是**任务进程与 API 进程分离**——API 只负责读写任务配置和结果，爬虫子进程独立跑。这样一次采集卡死 10 分钟也不会拖垮 Web UI。

> 迁移建议：你自己的项目至少要做到 `config / scraper / parser / storage / notify` 五个模块物理分文件。一个 800 行的 `spider.py` 是没法长期维护的。

---

## 二、风控识别：三层探针（最有价值的一段）

它不靠"报错了就重试"，而是把风控拆成**三个不同粒度的信号**，各自抛不同异常：

### 2.1 URL 层：登录态失效

```python
def _is_login_url(url: str) -> bool:
    lowered = url.lower()
    return "passport.goofish.com" in lowered or "mini_login" in lowered
```

每次 `page.goto()` / `wait_for_selector()` 之后都检查一次，命中抛 `LoginRequiredError`。
**关键洞察**：登录失效往往不报错，是**悄悄跳转到登录页**，然后你的选择器等 15 秒超时——你会误判成"页面改版"。

### 2.2 页面层：验证弹窗（2 秒超时判定法）

```python
baxia_dialog      = page.locator("div.baxia-dialog-mask")
middleware_widget = page.locator("div.J_MIDDLEWARE_FRAME_WIDGET")
try:
    await baxia_dialog.wait_for(state="visible", timeout=2000)
    raise RiskControlError("baxia-dialog")
except PlaywrightTimeoutError:
    pass   # 2 秒没出现 = 正常
```

**这个"短超时 + 异常即风控"的写法非常值得抄**：不要用 `is_visible()`（有竞态），用 `wait_for(timeout=2000)` 把"等待"变成"轮询判定"。

### 2.3 接口层：业务码校验

```python
ret_string = str(await safe_get(detail_json, "ret", default=[]))
if "FAIL_SYS_USER_VALIDATE" in ret_string:
    await asyncio.sleep(random.randint(3, 60))   # 先装人冷静一下
    raise RiskControlError("FAIL_SYS_USER_VALIDATE")
```

**注意顺序**：先随机长睡 3~60 秒，**再**抛异常。因为抛异常会触发轮换，立刻换号反而加重风控画像；先让这个会话"自然冷却"。

### 2.4 异常分层 → 上层决策

```
LoginRequiredError  → 更新登录态 / 换账号
RiskControlError    → 换代理 IP + 长冷却
TimeoutError        → 重试同账号
解析异常            → 记录并跳过单条，不中断任务
```

**过人之处**：异常类型即处置策略。没有这一层，你只能写一堆 `if "验证" in str(e)`。

---

## 三、熔断器 FailureGuard（可直接抄的完整设计）

目标：**登录态挂了别无限重试**。核心参数：

| 参数 | 默认 | 含义 |
|---|---|---|
| `TASK_FAILURE_THRESHOLD` | 3 | 连续失败几次开闸 |
| `TASK_FAILURE_PAUSE_SECONDS` | 86400 | 暂停时长（24h） |
| `TASK_FAILURE_GUARD_PATH` | `logs/task-failure-guard.json` | 状态文件 |
| `TASK_FAILURE_TZ` | `Asia/Shanghai` | 用于"每天只提醒一次" |

### 4 个精妙细节

**① 按"天"去重通知**：暂停期间不是每次调度都报警，而是 `last_notified_date != today` 才通知一次。避免 24 小时里被自己的报警刷屏。

**② cookie 文件 mtime 变化 → 自动恢复**
```python
def _cookie_changed(cookie_path, previous_mtime) -> bool:
    current = os.path.getmtime(cookie_path)
    return current > (previous_mtime + 1e-6)
```
用户重新导入登录态后，**下一次调度自动解除暂停**，不需要手动点"恢复"。这是把"运维动作"变成"文件系统事件"的漂亮解法。

**③ 原子写 + 文件锁**：先写 `.tmp` → `flush()` → `os.fsync()` → `os.replace()`；写入时用 `fcntl.flock` 加锁。因为状态文件会被 **API 进程和爬虫子进程同时读写**。
> Windows 上 `fcntl` 不存在，代码里用 `try/except` 吞掉了 —— 你在 Windows 部署时要换成 `msvcrt.locking` 或 `filelock` 库，这是它的一处短板。

**④ 损坏文件另存现场**
```python
except Exception:
    os.replace(path, f"{path}.corrupt.{int(time.time())}")
    return {}
```
配置/状态文件解析失败时**不删除也不覆盖**，改名留证据。这条应该写进你自己的所有状态文件读写里。

**⑤ 确定性错误立即熔断**：`min_failures_to_pause=1`。像"未找到可用的登录状态文件"这种，重试 3 次纯属浪费——一次就停。

---

## 四、轮换池 RotationPool（30 行，够用）

```python
class RotationPool:
    def __init__(self, items, blacklist_ttl=300, name=""):
        self.items = [RotationItem(value=i) for i in items if i]
        self.blacklist_ttl = max(0, int(blacklist_ttl))
        self._blacklist = {}          # value -> 解禁时间戳

    def available_items(self):
        self._cleanup_blacklist()
        return [i for i in self.items if i.value not in self._blacklist]

    def pick_random(self):
        c = self.available_items()
        return random.choice(c) if c else None

    def mark_bad(self, item, reason=""):
        item.last_error = reason
        if self.blacklist_ttl <= 0: return
        self._blacklist[item.value] = time.time() + self.blacklist_ttl
```

**设计要点**：
- 黑名单是 **TTL 而不是永久**（默认 300 秒）——代理常常是"临时抽风"，永久封禁会让池子越用越小
- 选号用 `random.choice` 而非轮询——轮询模式在风控看来是**周期性指纹**
- 同构复用：账号池和代理池用同一个类，`RotationPool(name="account")` / `RotationPool(name="proxy")`

**两种轮换模式**：`per_task`（每个任务换一次）和 `on_failure`（失败了才换）。前者摊薄单号请求量，后者节省配额。

---

## 五、登录态复用：浏览器托管头黑名单（最坑的一处）

它支持从 **Chrome 扩展导出的增强快照**（含 `env / headers / page / storage`），但注入时要把浏览器自己管的头全部剔掉：

```python
_BROWSER_MANAGED_EXTRA_HEADERS = {
    "accept", "accept-encoding", "authorization", "connection",
    "content-length", "content-type", "cookie", "host", "origin",
    "proxy-authorization", "referer",
    "sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site", "sec-fetch-user",
    "upgrade-insecure-requests", "user-agent",
}
```

**为什么必须剔**：快照里抓到的 header 是某个 **XHR 请求**的。如果你把带 `sec-fetch-mode: cors` 的头套到文档请求上，浏览器会把页面导航当成跨域 fetch，结果就是 **白屏 / 空白 DOM**——而你会以为是反爬。

> 这条命中了本库 [01 号文档](./01_anti_scraping_sop.md) 里"状态 200 但 body 只有几 KB"的表现。遇到白屏先查 header，别急着换指纹库。

### 反向利用：从快照 env 反推设备指纹

```python
# 从 env.navigator / screen / intl 反推
context_kwargs.update({
    "user_agent": ..., "viewport": ..., "device_scale_factor": ...,
    "locale": ..., "timezone_id": ..., "is_mobile": ..., "has_touch": ...,
})
```

**思路**：登录态是在哪台设备上拿的，采集就用同样的设备参数。UA 和 `is_mobile` 打架是最常见的自曝。

---

## 六、反检测套餐（组合拳，不是单个库）

### 6.1 启动参数
```python
"--disable-blink-features=AutomationControlled",  # 去掉 webdriver 痕迹
"--disable-dev-shm-usage",                        # 容器 /dev/shm 太小会崩
"--no-sandbox",
"--disable-setuid-sandbox",
"--disable-breakpad",
"--disable-crash-reporter",
"--disable-features=IsolateOrigins,site-per-process,Crashpad",
f"--crash-dumps-dir={crash_dumps_dir}",           # 固定到可写临时目录
```

> **容器专属坑**：Docker 里 Playwright 会拉起 `chrome_crashpad_handler`，默认 dump 路径指向 `/`（只读），crashpad 会不停重启自己吃掉内存。关掉 reporter + 固定 dump 目录，一个问题两个参数。

### 6.2 移动端 Context（完整的真实设备画像）
```python
{
  "user_agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 ...) Chrome/131 Mobile Safari/537.36",
  "viewport": {"width": 412, "height": 915},
  "device_scale_factor": 2.625,
  "is_mobile": True, "has_touch": True,
  "locale": "zh-CN", "timezone_id": "Asia/Shanghai",
  "permissions": ["geolocation"],
  "geolocation": {"longitude": 121.4737, "latitude": 31.2304},
  "color_scheme": "light",
}
```

### 6.3 init script 覆写 5 个指纹点
```javascript
Object.defineProperty(navigator, 'webdriver',    {get: () => undefined});
Object.defineProperty(navigator, 'plugins',      {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages',    {get: () => ['zh-CN','zh','en-US','en']});
Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 5});
window.chrome = {runtime: {}, loadTimes(){}, csi(){}};

const oq = navigator.permissions.query;
navigator.permissions.query = p => p.name === 'notifications'
  ? Promise.resolve({state: Notification.permission}) : oq(p);
```

### 6.4 拟人节奏表（这份数字比任何 stealth 库都值钱）

| 动作 | 延迟 |
|---|---|
| 进首页后 + 随机滚动 + 再停 | 1~2s + `scrollBy(0, rand*500+200)` + 1~2s |
| 搜索页加载后 | 1~3s |
| 点筛选条件后 | 2~4s |
| 区域每级点击 | 1.5~2s |
| **进详情页前** | 2~4s |
| **单个商品处理完** | 5~10s（主节流） |
| 关闭详情页后 | 2~4s |
| **翻页之间** | 10~15s（长休息） |
| 命中风控码 | randint(3, 60)s |

**心法**：风控模型的输入是"时间序列的规律性"。**只要每个间隔都是随机区间，就已经赢了一半**。所有 `asyncio.sleep(固定值)` 都是给风控送特征。

---

## 七、筛选条件不要拼 URL，要点 UI

闲鱼的搜索接口参数带签名（`sign` / `_m_h5_tk`），URL 拼参复用不了。它的做法：

```python
async with page.expect_response(is_search_results_response, timeout=20000) as ri:
    await page.click("text=包邮")
    await random_sleep(2, 4)
final_response = await ri.value
```

**`expect_response` + 点击**这个组合，把"点击 UI"变成"可编程的接口调用"——你既绕开了签名，又拿到了干净的 JSON。

### 三级区域联动：CSS Module 类名不能写死

```python
REGION_AREA_WRAP_SELECTOR = "[class*='areaWrap']:visible"     # 前缀匹配
REGION_COLUMN_SELECTOR    = ":scope > div"                    # 省/市/区三列
REGION_OPTION_SELECTOR    = "[class*='provItem']:visible"
REGION_SUBMIT_TEXT        = re.compile(r"查看(?:\d+|999\+)件宝贝")
```

> **核心教训**：现代前端用 CSS Modules，类名会带构建哈希（`areaWrap__3xK9d`）。**`[class*='xxx']` 前缀匹配 < 精确 class < XPath 绝对路径**，按可靠性从左到右递减。这个项目还专门修过一次 "Match region options by CSS-module prefix instead of stale hashes" —— 写死哈希的选择器是定时炸弹。

---

## 八、三重去重

```python
processed_links = load_processed_link_keys(keyword)   # ① 跨运行：历史结果集

unique_key = get_link_unique_key(item_data["商品链接"])
if unique_key in processed_links: continue            # ② 本次运行：内存 set
processed_links.add(unique_key)

record_market_snapshots(..., history_seen_item_ids)   # ③ 价格快照：item_id 级
```

**为什么要三层**：任务重启后内存 set 清空，必须靠持久化那层；而"同一个商品降价了再报一次"是**业务需求**而非重复，所以价格快照要独立维度。**去重粒度跟着业务语义走，不是简单的 URL 集合。**

---

## 九、AI 判定层：两个可直接抄的工程细节

### 9.1 用「参考范例 + 用户需求」生成判定标准（meta-prompt）

不让用户写 prompt，而是让用户写**自然语言需求**，再用一个 meta-prompt 生成结构化的《分析标准》：

```
你是提示词工程大师。根据【购买需求】，模仿【参考范例】的结构、语气、核心原则，
生成一份全新的【分析标准】，用于 AI 分析模块（代号 EagleEye）的思考指南。

要求：
1. 只输出正文，不要解释/标题/代码块标记
2. 保留 [V6.3 核心升级] 这类版本标记以保持格式一致
3. 把范例里所有 "MacBook" 相关内容替换为新商品
4. 思考并生成针对新商品类型的"一票否决硬性原则"和"危险信号清单"
```

**过人之处**：**few-shot 的模板本身被当成资产在版本迭代**（V6.3 → V6.4），提示词不再是散落在代码里的字符串，而是一份可 diff 的规格文件。
> 迁移建议：所有 AI 判定类任务都应该有 `prompts/xxx_criteria.txt` 这样的**参考范例文件**，用范例锚定输出结构，比几十行形容词有效得多。

### 9.2 reasoning 模型的截断判定（血泪教训）

```python
CRITERIA_MAX_OUTPUT_TOKENS = 8192   # 参考标准约 1k token，思考模型还要先输推理，800 会把正文截掉
_THINK_BLOCK_RE   = re.compile(r"<(?:think|thinking)>.*?</(?:think|thinking)>", re.I|re.S)
_UNCLOSED_THINK_RE = re.compile(r"<(?:think|thinking)>", re.I)

def _strip_reasoning_blocks(text):
    stripped = _THINK_BLOCK_RE.sub("", text).strip()
    if _UNCLOSED_THINK_RE.search(stripped):
        raise RuntimeError("思考过程占满输出长度，正文被截断……")
    if not stripped:
        raise RuntimeError("AI 没有生成正文。")
    return stripped
```

**三条可复用规则**：
1. 用 DeepSeek-R1 / QwQ / o 系列这类会输出 `<think>` 的模型时，**必须先剔 think 块再落库**，否则判定标准里混着推理废话
2. **未闭合的 `<think>` 就是"输出被 max_tokens 砍断"的可靠信号** —— 这是判断截断最便宜的方法，不用去猜 finish_reason
3. `max_output_tokens` 必须明显大于"参考文本长度 + 预期推理长度"，给 800 这种紧巴巴的值必翻车

### 9.3 AI 客户端双协议自动回退

```python
# 默认 Chat Completions；遇到"该 API 不支持"→ 自动切 Responses API
# response_format 不被支持 → 自动去掉该参数重试
```

**心法**：接第三方 OpenAI 兼容服务（中转站、国产模型）时，**能力探测要自动化**。写死 `responses` 或写死 `response_format=json_object`，换个服务商就全线崩。

---

## 十、关键词规则引擎：词边界（小细节，大坑）

```python
# 纯英数字关键词必须做前后边界检查
# 目标：搜索 "Q1" 不能匹配到 "Q1R5"
```

**为什么**：中文关键词 `in` 判定没问题，但英数字用 `in` 会疯狂误匹配。规则：
- 纯 `[A-Za-z0-9]+` 的关键词 → 用 `\b` 词边界或正则环视
- 含中文的关键词 → 可以直接 `in`
- **前后端必须用同一套规则**（它专门修过一次"后端引擎和前端表单显示一致性"）

---

## 十一、存储演进：JSONL → SQLite 的平滑迁移

```python
# 启动时：自动建库建表 → 若旧文件存在，导入一次 → 标记完成
```

**可抄的迁移策略**：
1. 主键用 `canonical_url` 唯一索引（天然幂等，重跑不炸）
2. 旧格式（`config.json` / `jsonl/` / `price_history/`）**只在首次启动导入一次**，之后挂载可保留也可删
3. 新字段用**自动迁移加列**（`ALTER TABLE ADD COLUMN` + 存在性检查），不写 migration 框架也能演进
4. 结果项加 `status` 列（`active / hidden / expired`），把"用户屏蔽了这条"变成数据状态而不是前端过滤

> 对照你自己的 AI-HR 项目：`canonical_url` 唯一键 + `status pending→pushed` 状态机，和这套是同一个思路，可以直接互相对齐。

---

## 十二、调度与运维细节

| 细节 | 做法 | 价值 |
|---|---|---|
| cron 兼容 | 支持 5 段 / 6 段 + `@hourly/@daily/@weekly/@monthly/@yearly` 别名 | 用户从别处抄来的表达式直接能用 |
| 下次运行时间 | 任务模型加 `next_run_at`，前端显示倒计时 | 用户不用猜"它到底跑没跑" |
| 日志清理 | `TASK_LOG_RETENTION_DAYS` 默认 7 天，定期删 | 长期跑必做，否则磁盘爆 |
| 图片临时目录 | `images/task_images_<task>/`，任务结束清理 | 同上 |
| 调试限流 | `debug_limit` 处理 N 条后停机 | 改代码时不用等全量跑完 |
| 代理黑名单 | `PROXY_BLACKLIST_TTL` | 见第四节 |

---

## 十三、通知渠道的"假成功"陷阱

它专门修过一个 bug：**PushPlus 返回 HTTP 200，但 body 里 `code != 0`**。

```python
# 正确做法：HTTP 200 之后还要查业务码
if resp.status_code == 200:
    body = resp.json()
    if body.get("code") != 0:
        raise NotificationError(body.get("msg"))
```

**通用规则**：所有 webhook 类通知（企业微信、Bark、Telegram、ntfy、PushPlus）都要**双层判定**：HTTP 状态码 + 业务返回码。只看状态码，你的"通知成功率"是假的。
另外：企业微信纯文本要发纯文本而不是 markdown，否则换行被吃掉。消息体里要带**任务名 + 命中原因 + 价格 + 链接**，缺一个用户就得回后台翻。

---

## ⚠️ 避坑指南

- **不要在 FastAPI 进程里直接跑 Playwright 长任务**：一个任务卡住就阻塞事件循环。用子进程 + 结果落库。
- **不要写死 CSS 类名哈希**：见第七节。选择器优先级 `[class*=]` > 精确 class > XPath。
- **不要把登录快照的全部 header 塞进 context**：见第五节，会白屏。
- **不要用固定 `sleep`**：见第 6.4 节，随机区间才有意义。
- **不要在 Windows 上依赖 `fcntl`**：状态文件锁要换 `filelock`。
- **不要只看 HTTP 200 就认为通知成功**：见第十三节。
- **不要把 `max_output_tokens` 设成"刚好够正文"**：reasoning 模型会先吃掉预算。
- **不要在风控命中后立刻换号重试**：先冷 3~60 秒，否则新号第一时间就被打上标记。
- **不要永久拉黑代理/账号**：用 TTL，代理抽风是常态。
