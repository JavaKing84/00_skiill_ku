---
name: web-scraping-index
type: manifest
version: 2.1
entry: ../SKILL.md
count: 8
---

# 技能清单（机器可读索引）

> 用途：按需加载。每篇文档头部都有同样的 frontmatter，可先扫 frontmatter 再决定是否展开正文。
> **人类入口** → [README.md](../../README.md)　**模型入口** → [SKILL.md](../../SKILL.md)

```yaml
skills:
  - id: WS-01
    file: 01_anti_scraping_sop.md
    title: 反爬侦察与破局 SOP
    level: 通用
    phase: [P1, P2]
    triggers: [403, 503, 验证码, 空壳, 数据被篡改, 频率限制, 不知道被什么拦]
    use_when: 目标站点无法访问、返回 403/503、弹验证、返回空壳、数据不对，且尚未定性拦截层级
    skip_when: 已确定是 CDP 级检测（→ WS-02）或已确定是签名参数（→ WS-07）
    outputs: [分层归因结论, 武器选型表, 工程化清单]
    next: [WS-02, WS-05, WS-06]

  - id: WS-02
    file: 02_cdp_detection_bypass.md
    title: 绕过 CDP 级检测实战
    level: 进阶
    phase: [P1, P2, P3]
    triggers: [about:blank, body 长度 0~15, 状态 200 无内容, loading 骨架, playwright 拿不到数据]
    use_when: 上了真内核浏览器仍是空壳；page.url 变 about:blank；控制台出现 window.close 警告
    skip_when: 页面正常渲染只是字段缺失（那是解析问题，不是检测问题）
    outputs: [patchright 持久化模板, 三项验证指标]
    next: [WS-06, WS-05]

  - id: WS-03
    file: 03_deep_site_scraper_engineering.md
    title: 单站点深度采集的工程化范式
    level: 系统
    phase: [P4]
    triggers: [长期跑, 多任务, 要熔断, 要轮换, 账号池, 登录态, 定时监控, 要通知]
    use_when: 目标需要 7x24 稳定运行、有登录态、有风控、要 AI 二次判定
    skip_when: 一次性抓取；或目标是多源低频聚合（→ WS-04）
    outputs: [五层项目骨架, FailureGuard, RotationPool, 拟人节奏表, 三重去重]
    next: [WS-06]

  - id: WS-04
    file: 04_aggregator_pipeline_design.md
    title: 采集与 API 服务解耦的聚合架构
    level: 架构
    phase: [P4]
    triggers: [多数据源, 对外提供接口, 高 QPS, 数据要给人/AI 消费, 抓取常被封但接口不能挂]
    use_when: 几十个源、更新频率低、需要对外供数或给 AI 消费
    skip_when: 单站实时监控（→ WS-03）
    outputs: [三段式解耦架构, encoding 多形态, 统一响应契约, llms.txt 规范]
    next: [WS-06]

  - id: WS-05
    file: 05_failure_taxonomy.md
    title: 故障查表（症状 → 根因 → 动作 → 验证）
    level: 排障
    phase: [P1, P3, P4, P5]
    triggers: [报错, 昨天能跑今天不行, 数据不对, 超时, 空结果, 验证码, 429, 白屏]
    use_when: 任何"它不工作了"的时刻。先查表，再决定读哪篇
    skip_when: 全新项目尚未动手（→ 从 SKILL.md P0 开始）
    outputs: [根因判定, 单条可执行动作, 验证命令]
    next: [对应主文档]

  - id: WS-06
    file: 06_code_templates.md
    title: 可运行代码模板
    level: 实现
    phase: [P3, P4]
    triggers: [要代码, 写个脚本, 抄模板, 骨架]
    use_when: 已经定性完成，需要落地实现
    skip_when: 还没定性（先做 P0/P1，否则抄错模板）
    outputs: [侦察脚本, 浏览器模板, 风控探针, 熔断器, 轮换池, 快照 API, 去重]
    next: []

  - id: WS-07
    file: 07_js_signature_reverse.md
    title: 签名参数与加密参数逆向
    level: 高难
    phase: [P1, P2, P3]
    triggers: [sign, token, 加密参数, 时间戳校验, 请求签名, 参数看不懂, JS 加密]
    use_when: 接口存在无法直接复现的签名/加密参数
    skip_when: 接口参数全是明文（那就别碰逆向，直接请求）
    outputs: [三条路线决策树, 定位手法, 补环境清单, 验证方法]
    next: [WS-06]

  - id: WS-08
    file: 08_unified_collection_contract.md
    title: 统一采集接口契约（素材 / 情报双适配器）
    level: 架构
    phase: [P2, P3, P4]
    triggers: [统一格式, manifest, 去重, 断点, 素材清单, 情报入库, 元数据, 速率限制]
    use_when: 任何落盘文件或写入情报库的采集任务；素材采集与 TechRadar 复用同一底座
    skip_when: 一次性只读侦察且不落盘（走 P0 四连命令）
    outputs: [collection-manifest-v1, CrawlPolicy, RateLimiter, Checkpoint, 两级去重]
    next: [WS-05, WS-06]
```

## 文档间依赖

```
SKILL.md ──┬─> 01 ──┬─> 02
           │        └─> 05
           ├─> 03 ──> 06
           ├─> 04 ──> 06
           ├─> 07 ──┬─> 06
           │        └─> 05
           └─> 05（横切：任何阶段都可能用）
```

`05` 和 `06` 是横切文档：任何阶段都可能需要，但与主线无强依赖。
