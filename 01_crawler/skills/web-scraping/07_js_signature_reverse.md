---
id: WS-07
title: 签名参数与加密参数逆向
level: 高难
phase: [P1, P2, P3]
triggers: [sign, token, 加密参数, 时间戳校验, 请求签名, 参数看不懂, JS 加密, 接口 403 签名错误]
read_when: 接口存在无法直接复现的签名/加密参数
skip_when: 接口参数全是明文（那就别碰逆向，直接请求）
outputs: [三条路线决策树, 定位手法, 补环境清单, 验证方法, 成本评估]
next: [WS-06]
---

# 🔐 Skill 07: 签名参数逆向

> 这是"高难度爬虫"真正的分水岭。前面几篇解决的是"能不能进得去"，这一篇解决的是"请求能不能被接受"。
> **核心心法：不要试图读懂混淆代码，要试图让它替你干活。** 三种路线，按成本从低到高，别一上来就抠代码。

## 🎯 什么时候需要这篇

接口出现了下列任一特征：

```bash
# 特征 1：参数里有可疑字段
?sign=8f14e45fceea167a5a36dedd4bea2543&t=1730779200&nonce=abc123
?X-Sign=xxx&X-Ts=xxx&X-Nonce=xxx

# 特征 2：请求体是密文
{"data":"U2FsdGVkX1+abc...=="}          # base64 → 可能是 AES
{"payload":"7b226b223a..."}             # base64 of JSON

# 特征 3：同样的参数，改一个字符就 403 / "签名错误"
{"code":40001,"msg":"invalid signature"}
```

**判定前置**：先用浏览器手动操作一次，把成功请求 "Copy as cURL" 出来直接跑。
- 通了 → 不是签名问题，是 header/cookie 问题（回 WS-05 的 B 组）
- 不通 → 确认是签名/时间戳/一次性 token，继续往下

---

## 一、三条路线（决策树，先看这个）

```
找到生成签名的那段 JS
        │
        ├─ 依赖大量浏览器环境（window/document/canvas/deviceId）
        │   └─▶ 路线 A：浏览器内执行（page.evaluate 调用页面函数）
        │         成本最低、最稳、速度最慢（~50-200ms/次）
        │
        ├─ 纯算法（MD5/AES/HMAC），环境依赖少
        │   └─▶ 路线 C：Python 重写
        │         最快（~0.1ms/次），但需要真正读懂算法
        │
        └─ 纯算法但混淆严重（控制流平坦化、字符串加密、wasm）
            └─▶ 路线 B：扣代码 + 补环境（Node / PyMiniRacer 跑原版 JS）
                  中等成本，保真度最高
```

### 决策规则

| 情况 | 选 |
|---|---|
| 只要跑通、量不大（< 1 万次/天） | **A**（别折腾，A 最省时间） |
| 量大、要并发、要脱离浏览器 | B 或 C |
| 算法清晰（就是 `md5(拼接串)`） | C（20 行搞定） |
| 算法里混了 `canvas` 指纹、`performance.now`、设备信息 | A 或 B（C 基本不可能） |
| 有 `.wasm` 文件 | A（在浏览器里调 wasm，别想反编译） |
| 混淆到 `_0x4a2b['\x61\x62']` 满地都是 | B（让它自己跑，不读它） |

> **最容易犯的错**：一上来就抠代码、反混淆、读三天。先花 30 分钟试路线 A —— 它往往 20 行就能跑通。

---

## 二、定位入口：找到"生成签名的那一行"

这是整件事唯一需要耐心的地方。六种手法，按成功率排序。

### 手法 1：XHR/fetch 断点（最直接）

```
DevTools → Sources → 右侧 XHR/fetch Breakpoints → + → 输入接口 URL 的关键片段（如 /api/list）
→ 触发请求 → 断在发请求的那一刻 → 看右侧 Call Stack
```

**读调用栈的方法**：从栈顶往下点，**找第一个"看起来像业务代码"的帧**（不是 `axios`、`webpack`、`chunk-vendors`）。
那一帧附近通常就是 `headers: { sign: xxx }` 的组装处，往上一行就是签名函数调用。

### 手法 2：全局搜索参数名
```
Ctrl+Shift+F → 搜 "sign" / "signature" / "X-Sign" / "_sign"
过滤：只搜 .js，排除 .min.js（如果只有 min.js 就搜它，配合断点）
```

### 手法 3：Hook 关键函数（通用性最强）

在**页面加载之前**注入（DevTools Snippets / Playwright `add_init_script`）：

```javascript
// 谁调用了 JSON.stringify？—— 加密前通常会序列化
const _stringify = JSON.stringify;
JSON.stringify = function (...args) {
    const r = _stringify.apply(this, args);
    console.trace("[stringify]", r.slice(0, 200));
    return r;
};

// 谁读了时间戳？—— 签名几乎都含时间戳
const _now = Date.now;
Date.now = function () { console.trace("[Date.now]", _now()); return _now(); };

// 谁在设请求头？—— 签名最终要落到 header
const _setHeader = XMLHttpRequest.prototype.setRequestHeader;
XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
    if (/sign|token|ts|nonce/i.test(k)) console.warn("[header]", k, v);
    return _setHeader.apply(this, arguments);
};
```

**这招的威力**：不用搜代码，让它自己告诉你调用链。`console.trace` 直接打出完整栈。

### 手法 4：搜索加密库特征串
```
"md5" "sha1" "sha256" "hmac" "aes" "encrypt" "CryptoJS" "JSEncrypt" "sm2" "sm4"
"__sign" "getSign" "genSign" "makeSign" "calcSign"
```
命中 `CryptoJS.AES.encrypt(` → 找它的 `key` 和 `iv` 从哪来。
命中 `JSEncrypt` → RSA 公钥就硬编码在附近。

### 手法 5：反调试绕过
遇到 `debugger` 死循环：
- Sources 面板右键该行 → **Never pause here**
- 或全局搜索 `debugger`，把所在函数整体替换为空函数（用 Overrides 本地覆盖）
- 或用"条件断点 = false"跳过

### 手法 6：看 initiator
Network → 选中请求 → Initiator 标签 → 直接给调用链，点击跳到源码。

---

## 三、路线 A：浏览器内执行（首选）

**前提**：页面里已经有可用的签名函数（全局挂载，或能从 webpack 模块里取出来）。

### 3.1 最简单的形态

```python
# 前提：已用 T-03 建立持久化 context，且页面已加载
def sign_in_page(page, params: dict) -> dict:
    return page.evaluate("""(p) => {
        // 把参数塞进去，调用页面自己的签名函数
        return { ...p, sign: window.__SIGN__(p) };
    }""", params)
```

### 3.2 真实场景：函数不在全局

先探一下它在哪：

```javascript
// 在 Console 里跑，找候选
Object.keys(window).filter(k => /sign|encrypt|token/i.test(k))
// 找 webpack 模块（现代打包产物常见）
Object.keys(window.webpackChunkxxx || {})
```

webpack 模块的取法（思路：遍历 `__webpack_require__.c` 找导出含 sign 函数的模块）：

```javascript
(() => {
  const req = window.__webpack_require__ || (window.webpackChunk && null);
  const cache = req && req.c;
  if (!cache) return "no webpack cache";
  const hits = [];
  for (const id in cache) {
    const ex = cache[id] && cache[id].exports;
    if (!ex) continue;
    for (const k in ex) {
      if (typeof ex[k] === "function" && /sign|encrypt/i.test(k)) hits.push([id, k]);
    }
  }
  return hits;
})()
```

### 3.3 批量签名（把 RTT 摊薄，关键性能技巧）

一次 `evaluate` 里签 N 个，而不是 N 次调用：

```python
def sign_batch(page, items: list[dict]) -> list[dict]:
    return page.evaluate("""(items) => items.map(it => ({
        ...it,
        sign: window.__SIGN__(it)
    }))""", items)

# 用法：一次签 20 个，平均成本从 150ms 降到 10ms
for chunk in [items[i:i+20] for i in range(0, len(items), 20)]:
    signed = sign_batch(page, chunk)
```

### 3.4 资源释放

签名用的页面**不要关**，但也不要让它一直加载。做法：
- 打开一个**空白页**（`about:blank` 不行，要在同源页面上执行）
- 加载目标站首页（不用进具体页面），函数已经注册好
- 签名全程复用这一个 page

> **A 路线的边界**：如果签名函数内部读了 `performance.now()`、`Math.random()`、`canvas` 指纹，那你每次签出来的值**本来就应该不一样**——这不是 bug。验证时要按"服务端接受"判定，不是按"值相同"判定。

---

## 四、路线 C：Python 重写（量大的最终形态）

只有确认算法是纯函数（输入 → 输出，无环境依赖）才走这条。

### 4.1 常见形态速查

| 观察到 | 大概率是 | 关键信息 |
|---|---|---|
| 32 位十六进制 | MD5 | 拼接顺序 + 是否有固定 salt |
| 40 位十六进制 | SHA1 | 同上 |
| 64 位十六进制 | SHA256 | 同上 |
| 带 `=` / `==` 结尾、长 24 或 44 | Base64（可能是 AES 密文） | 找 key/iv |
| 变长、字母数字混合、无规律 | Base64 后 URL-safe 变形 | 先 `-`→`+`、`_`→`/` 再解 |
| 很长的 hex（>256） | RSA 签名 | 私钥在客户端（少见）或公钥加密 |

### 4.2 拼接顺序的确定方法

同一组参数，**只改一个值**，看 sign 怎么变，反推拼接串：

```python
# 假设怀疑 sign = md5(a + b + salt)
# 在浏览器里连发两次请求，只改 b，记录 sign
# 再用 Python 穷举拼接顺序与分隔符，匹配上就找到了
import hashlib, itertools

def try_orders(params: dict, target: str, salts: list[str]):
    keys = list(params)
    for perm in itertools.permutations(keys):
        for sep in ("", "&", "|", ","):
            for salt in salts:
                base = sep.join(f"{k}={params[k]}" for k in perm) + salt
                for algo in ("md5", "sha1", "sha256"):
                    if hashlib.new(algo, base.encode()).hexdigest() == target:
                        return f"{algo}({sep.join(perm)}{'+salt' if salt else ''})"
    return None
```

**salt 从哪来**：搜索 JS 里的长字符串常量、`appKey`、`secret`、`_key`。常见硬编码在 `config.js` / `constants` 里。

### 4.3 AES 常见坑

```python
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

# JS CryptoJS.AES.encrypt(text, key) 默认：CBC + Pkcs7 + key 当字符串走 OpenSSL KDF
# Python 侧对应：
#   key 用 md5(key).digest()（CryptoJS 的 OpenSSL 兼容模式会这么处理）
#   密文 base64 解码后前 8 字节是 "Salted__" 魔术头
```

**验证方法**：加密结果 base64 解码后如果以 `b"Salted__"` 开头，说明是 CryptoJS 默认 KDF —— 直接用现成库解，别自己推。

---

## 五、路线 B：扣代码 + 补环境

混淆严重又想提性能时的折中：**把原版 JS 抠出来，在 Node 里跑，缺什么补什么。**

### 5.1 最小补环境清单

```javascript
// env.js —— Node 里跑浏览器 JS 的地基
global.window = global;
global.self = global;
global.navigator = {
  userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           + "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  platform: "Win32", language: "zh-CN", languages: ["zh-CN", "zh"],
  webdriver: undefined, hardwareConcurrency: 8,
};
global.document = { cookie: "", createElement: () => ({ getContext: () => null }) };
global.location = { href: "https://target.com/", protocol: "https:", host: "target.com" };
global.screen = { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040 };
global.localStorage = { getItem: () => null, setItem: () => {} };

// 编码/加密相关的必备项
global.atob = s => Buffer.from(s, "base64").toString("binary");
global.btoa = s => Buffer.from(s, "binary").toString("base64");
global.TextEncoder = require("util").TextEncoder;
global.TextDecoder = require("util").TextDecoder;
global.crypto = { getRandomValues: arr => require("crypto").randomFillSync(arr) };
```

### 5.2 报错 → 补什么（对照表）

| 报错 | 缺什么 |
|---|---|
| `window is not defined` | `global.window = global` |
| `document is not defined` | `global.document = {...}` |
| `navigator is not defined` | `global.navigator = {...}` |
| `xxx is not a function`（在 `_0x...` 后） | 某个库没抠全，往前找依赖 |
| `Cannot read property 'getContext' of null` | `document.createElement` 返回值要带 `getContext` |
| `crypto is not defined` | `global.crypto` |
| `setTimeout is not defined` | Node 有，但可能是 `window.setTimeout` |
| `atob is not defined` | 见上面清单 |

### 5.3 怎么调

```python
# py_mini_racer：Python 里直接跑 JS，比起 Node 进程快
from py_mini_racer import MiniRacer

ctx = MiniRacer()
ctx.eval(open("env.js", encoding="utf-8").read())
ctx.eval(open("sign.js", encoding="utf-8").read())     # 抠出来的代码

sign = ctx.call("getSign", {"a": 1, "b": 2})
```

> **扣代码的最小集**：从目标函数往上，只抠它真正用到的函数和常量。抠多了必然带进一堆补不完的环境。
> 判断方法：先在 Node 里跑，报错缺哪个就补哪个，直到跑通 —— **不要预先补全**。

---

## 六、验证：怎么证明你真的破了

**四步验证，一步都不能省。**

```python
# ① 确定性检查
s1 = gen_sign(params); s2 = gen_sign(params)
assert s1 == s2, "结果不稳定 —— 可能有 Math.random / 时间戳 / 未初始化的变量"

# ② 与浏览器对照（最硬的证据）
# 在浏览器里用同样的 params 调一次，把结果抄出来对比
assert s1 == browser_sign, f"不一致: py={s1} browser={browser_sign}"

# ③ 服务端接受（终极标准）
resp = requests.get(url, params={**params, "sign": s1}, headers=headers)
assert resp.status_code == 200 and resp.json().get("code") == 0, resp.text[:300]

# ④ 反向验证（证明你找的是真校验）
bad = params.copy(); bad["page"] = 2                    # 改一个参与签名的参数，但 sign 不变
assert requests.get(url, params={**bad, "sign": s1}).status_code != 200, \
    "改了参数却还能通过 —— 说明 sign 里没含这个参数，或者服务端没校验"
```

**④ 是最容易被跳过、也最有价值的一步**：它能告诉你**哪些参数真的参与签名**、服务端到底校验没校验。很多"破解成功"其实是服务端根本没查。

---

## 七、坑清单

| 坑 | 现象 | 处理 |
|---|---|---|
| 时间戳被缓存 | 页面加载时算一次，之后复用 | 签名函数要传入当前 ts，别用页面里那个变量 |
| 参数顺序敏感 | 同样的参数不同顺序 → 不同 sign | 严格按 JS 里的遍历顺序构造（`Object.keys` 顺序） |
| 编码不一致 | 中文参数签名对不上 | JS 是 UTF-8，Python 别用 GBK；`ensure_ascii=False` |
| 大小写 | hex 大写 vs 小写 | 统一 `.lower()` 或 `.upper()` 试两次 |
| URL 编码差异 | `+` vs `%20`、`/` 是否编码 | JS `encodeURIComponent` 不编码 `/`，Python `quote` 默认也不编码，但 `quote_plus` 会 |
| 一次性 token | 第一次成功第二次失败 | token 要从页面/接口动态取，并做缓存 + 刷新 |
| 设备指纹入参 | 换机器就失效 | 走路线 A（让浏览器自己提供环境） |
| wasm 加密 | 找不到 JS 逻辑 | 走路线 A，别反编译 wasm |
| 签名含 body 哈希 | GET 能过，POST 报错 | 签名对象要包含 body（先 `JSON.stringify` 再签） |
| 反调试死循环 | 一开 DevTools 就卡死 | Never pause here / 条件断点 / Overrides 覆盖 |

---

## 八、成本评估：什么时候该放弃

逆向是有天花板的。**投入产出比在下面这些情况下明显不合理**：

| 信号 | 建议 |
|---|---|
| 有 `.wasm` + 大量环境检测 | 走路线 A，别想纯算法复现 |
| 签名依赖 canvas/WebGL 指纹 | 走路线 A |
| 每 2 周换一次算法 | 走路线 A（不用维护） |
| 站点有官方开放 API | **直接用官方 API**，别逆向 |
| 数据有等价替代源 | 换源，比逆向便宜一个数量级 |
| 需要实时 + 大数据量 + 强反爬 | 重新评估需求，可能不值得 |

> **一句话**：路线 A 是"用浏览器当签名机"，路线 C 是"把浏览器扔掉"。前者能解决 90% 的问题且几乎不会过期；后者性能高但维护成本高。
> **默认选 A，只在性能真的成为瓶颈时才迁移到 B/C。**

---

## 九、合规边界

- 只对**你有权访问的数据**做这件事（自己的账号、公开数据、授权测试）
- 不绕过付费墙去取付费内容
- 不伪造他人身份、不冒用他人账号
- 控制频率，不造成服务负担
- 遵循目标站的服务条款与 robots 协议；有官方 API 就优先用官方 API
