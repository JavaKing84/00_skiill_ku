---
id: WS-02
title: 绕过 CDP 级检测实战
level: 进阶
phase: [P1, P2, P3]
triggers: [about:blank, body 长度 0~15, 状态 200 无内容, loading 骨架, playwright 拿不到数据]
read_when: 上了真内核浏览器仍是空壳；page.url 变 about:blank；控制台出现 window.close 警告
skip_when: 页面正常渲染只是字段缺失（那是解析问题，不是检测问题）
outputs: [patchright 持久化模板, 三项验证指标]
next: [WS-06, WS-05]
---

# 🛠️ Skill 02: 绕过 CDP 级检测实战

> 微观进阶实战。以 BOSS 直聘（zhipin.com）为样本，记录一次真实的破局过程。
> 实测环境：Windows / Python 3.14 / patchright 1.64.3 / Edge 内核（Chromium 143）
> **所属阶段**：P1 定性 / P2 选型 / P3 打通 ｜ 前置：WS-01 ｜ 后续：WS-06、WS-05

## 🎯 适用场景

已经上到 Playwright（甚至换成真实 Chrome/Edge 内核、加了 `playwright-stealth`、改了 UA 和时区），但页面依然拿不到数据。典型特征是**请求并不报错**——状态码 200、不弹验证码、也不跳验证页，可你就是拿不到内容。

## 🔬 三步定位：这不是普通反爬

### 症状清单

| 你观察到的现象 | 说明 |
| --- | --- |
| 状态码 200，但 `page.content()` 只有几 KB | 拿到的是 SPA 空壳，数据靠 JS 渲染，而渲染被掐断了 |
| `page.inner_text('body')` 长度是 0～15 | 页面框架在，内容一个字都没进来 |
| 截图只有极淡的 logo / loading 骨架 | 前端一直卡在初始化 |
| `page.url` 变成 `about:blank` | **决定性证据**，见下 |
| 控制台最后一条：`Scripts may close only the windows that were opened by them.` | 脚本在尝试 `window.close()` 自毁 |

### 决定性证据

正常反爬会给你 **403、验证码页、跳登录页**。而 CDP 级检测的做法是：检测到自动化环境后，**前端 JS 主动把页面切到 `about:blank` 并尝试自关闭窗口**。

所以排查时别只看状态码，一定要打这三行：

```python
print("url      :", page.url)          # 是不是 about:blank
print("body_len :", len(page.inner_text("body")))   # 是不是 0～15
print("html_len :", len(page.content()))            # 是不是只有几 KB
```

这三行如果命中，就**不用再折腾 UA、时区、Cookie、代理**了——方向是 CDP，不是指纹。

## 🧠 为什么 playwright-stealth 在这里完全无效

`playwright-stealth` 是**在页面 JS 层改属性值**，它补的是表层：

- `navigator.webdriver` 改成 `undefined`
- `navigator.plugins`、`navigator.languages` 造假
- `window.chrome` 补一个空壳

而 CDP 检测发生在**更底下的协议层**，两者根本不在一个维度上：

1. **`Runtime.enable` / `Console.enable` 的副作用**：Playwright 建立连接时会启用这些域。页面只要 `console.debug(obj)` 传一个带 getter 的对象，如果这个 getter 被触发两次（一次本地打日志、一次被协议序列化上报），就能判定"有人在监听控制台"。这类探针 stealth 补不了。
2. **注入痕迹留在调用栈里**：所有 `add_init_script` 注入的补丁，最终都会在 `Error().stack` 里露出不属于页面自身的脚本帧。检测脚本抓一次栈就能发现异常。
3. **绑定对象能直接被扫**：Playwright 通过 `page.exposeBinding` 注入的函数会挂在 window 上（形如 `window.__playwright__binding__*`）。页面用 `Object.keys(window)` 一过就能发现。
4. **自相矛盾的特征**：手工设了 Chrome 141 的 UA，内核却是 143；或者 `navigator.webdriver` 是 undefined 但 `--enable-automation` 的其它痕迹还在。手工补丁越多，矛盾点越多。

> 一句话总结：**stealth 是化妆，CDP 检测是查身份证。** 化妆化得再细，证件号对不上照样过不去。

## 🛠️ 解决方案：patchright + 持久化上下文

### 为什么是 patchright

`patchright` 是 Playwright 的**反检测分支**，API 完全一致（`from patchright.sync_api import sync_playwright`），但它从协议层做了修正：

- 不再无脑 `Runtime.enable`，改用不触发探针的调用方式
- 关闭 `Console.enable`，堵掉 `console.debug` 时间差检测
- 清理 Playwright 注入的绑定对象与脚本痕迹
- 修正 `--enable-automation` 相关的启动参数

### 为什么必须用 persistent context

`launch()` + `storage_state` 每次都是全新的临时 profile，Cookie 之外的 IndexedDB、localStorage、指纹种子全部重置，反而更像"机器人每次都是干净身份"。

`launch_persistent_context()` 会固定一个用户数据目录，登录态、缓存、指纹都自然沉淀，行为和真人浏览器一致。

### 核心代码（已验证可跑）

先装：

```bash
pip install patchright -i https://pypi.tuna.tsinghua.edu.cn/simple
```

最小可跑版本：

```python
from patchright.sync_api import sync_playwright

PROFILE = "./browser_profile"     # 持久化用户数据目录，登录一次以后都能用

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE,
        channel="msedge",         # 优先用真实内核：chrome / msedge
        headless=False,           # 首次登录务必有头，方便扫码
        no_viewport=True,         # 关键：不要伪造固定视口，用真实窗口尺寸
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.zhipin.com/web/geek/job?query=python",
              wait_until="domcontentloaded")
    page.wait_for_timeout(5000)

    print("url      :", page.url)
    print("body_len :", len(page.inner_text("body")))
    print("cards    :", page.locator("li.job-card-wrapper").count())

    ctx.close()
```

带登录态判断的完整形态（判断依据：cookie 里出现 `zp_at` 即已登录）：

```python
def is_logged_in(ctx) -> bool:
    return "zp_at" in {c["name"] for c in ctx.cookies()}


def ensure_login(ctx):
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.zhipin.com/web/user/", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    # 默认是验证码登录，切到扫码标签
    for sel in ["text=APP扫码登录", ".tab-qr-code", "text=扫码登录"]:
        loc = page.locator(sel).first
        if loc.count() and loc.is_visible():
            loc.click(timeout=3000)
            break

    print("请用手机扫码登录，最多等 150 秒 ...")
    import time
    deadline = time.time() + 150
    while time.time() < deadline:
        if is_logged_in(ctx):
            print("[OK] 登录成功，登录态已写入 profile，下次启动自动复用")
            return True
        time.sleep(1.5)
    return False
```

### 三个"不要"（违反任何一条都可能前功尽弃）

1. **不要 `add_init_script` 注入 stealth 补丁**。patchright 已经处理了，再注入等于在干净指纹上留下一串可疑脚本帧。
2. **不要覆盖 `user_agent`**。真实内核的 UA 天然正确；手写 UA 与内核版本对不上是典型自曝。
3. **不要设 `viewport={"width": 1440, "height": 900}`**。用 `no_viewport=True` 让窗口尺寸跟随真实窗口，否则 `screen.width` 与 `innerWidth` 会露出矛盾。

## ✅ 怎么验证生效

改完立刻跑这三项，任一项不达标就说明没绕过：

| 检查项 | 期望值 |
| --- | --- |
| `page.url` | 仍是目标页，**不是** `about:blank` |
| `len(page.inner_text("body"))` | 几百以上（不是 0～15） |
| 目标元素计数 | `li.job-card-wrapper` > 0 |

进阶可以用公开的指纹测试站自查：`bot.sannysoft.com`、`abrahamjuliot.github.io/creepjs`。重点看 `webdriver`、`WebGL renderer`、`plugins` 三项是否自然。

## 📊 方案对比

| 方案 | 能否过 CDP 检测 | 成本 | 备注 |
| --- | --- | --- | --- |
| 裸 Playwright + 自带 Chromium | ❌ | 低 | 状态 200 但 body 为空壳 |
| Playwright + 真实 Edge/Chrome | ❌ | 低 | 换了内核也一样，检测在协议层 |
| Playwright + playwright-stealth | ❌ | 中 | 只补 JS 属性，不碰协议层 |
| **patchright + persistent context** | ✅ | 中 | 本次实测方案，登录页与列表页均正常 |
| Camoufox（Firefox 基底） | ✅ | 中高 | 指纹面不同，需重写选择器等逻辑 |
| 住宅代理 + 打码平台 | ✅ | 高（烧钱） | 客观有效，但属付费方案，**本库不采用**；同等效果优先用降频 + 自建代理池 |

## ⚠️ 避坑指南

- **版本对不上不要去 `playwright install`**：本机已有内核时，`playwright` 期望的版本号常常差几档（例如期望 1248、本地只有 1243），直接 `channel="msedge"` 用系统浏览器绕开，省下几百 MB 下载。
- **登录墙和 CDP 检测要分开处理**：登录是一次性的（扫码后进 profile），检测是每次请求都要面对的。别把两者混成一个问题。
- **别忘了限速**：绕过检测不等于可以狂刷。翻页间隔 4～7 秒、页内轻微滚动，比任何指纹补丁都更能延长生命周期。
- **只在合规范围内用**：这类技术用于自己有权访问的数据、个人求职研究或授权测试。绕过技术保护措施去批量抓取他人数据，风险自负。
