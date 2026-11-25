# 🧠 Engineering Skills Library — 爬虫技能库

> 位置：`D:\00_skiill_ku\01_crawler`　|　总览见 [../README.md](../README.md)
> 最近整理：2026-11-15

本库分三部分，各司其职：

| 部分 | 位置 | 是什么 | 谁来用 |
|---|---|---|---|
| **① 自研爬虫执行协议** | `SKILL.md` + `skills/web-scraping/`（索引 1 篇 + WS-01～08 共 8 篇） | 自己沉淀的 P0→P5 方法论、SOP、故障查表、代码模板、统一采集契约 | 模型按协议执行；人按需学习 |
| **② GitHub 热门技能收藏** | `repos/`（7 个仓库） | 从 GitHub 精选的高星爬虫技能源码 | 想装新技能、想抄成熟方案时查 |
| **③ 浏览器运行时** | 实际位置 `D:\00_skiill_ku\01_crawler\runtime\`（Camoufox 2444.4 MB / Playwright 705.6 MB，2026-11-17 实测） | 浏览器内核二进制（勿动、勿删，体积大）；由环境变量 `PLAYWRIGHT_BROWSERS_PATH` 接管，**库内原同名目录已迁移不存在** | 被 ①② 的脚本调用 |

**双入口设计**：人看 README，模型看 SKILL.md。

| 入口 | 文件 | 给谁 |
|---|---|---|
| 🧑 **人类入口** | 本文件 | 想学、想查、想理解为什么 |
| 🤖 **模型入口** | [SKILL.md](./SKILL.md) | 塞给大模型，让它据此执行高难度爬虫 |
| 📇 **机器清单** | [skills/web-scraping/00_index.md](./skills/web-scraping/00_index.md) | YAML manifest，供程序按需加载 |

> 为什么分两个入口：**人需要理解，模型需要协议**。
> 让人读的文档写"为什么这么做"，给模型读的文档写"按什么顺序做、什么时候停、怎么证明做成了"。

---

## ① 自研协议库：web-scraping（爬虫 / 反爬 / 浏览器自动化）

| # | 文档 | 一句话 | 层级 |
|---|---|---|---|
| — | [SKILL.md](./SKILL.md) | **执行协议**：P0→P5 六阶段 + 九条硬约束 + 路由表 + 术语归一 | 入口 |
| — | [00_index.md](./skills/web-scraping/00_index.md) | 技能清单（YAML），带 triggers / read_when / skip_when | 索引 |
| 01 | [反爬侦察与破局 SOP](./skills/web-scraping/01_anti_scraping_sop.md) | 先定性再选武器。四层排查 + 武器匹配表 | 通用 |
| 02 | [绕过 CDP 级检测实战](./skills/web-scraping/02_cdp_detection_bypass.md) | `about:blank` 的真相：patchright + 持久化上下文 | 进阶 |
| 03 | [单站点深度采集的工程化范式](./skills/web-scraping/03_deep_site_scraper_engineering.md) | 把脚本做成系统：分层、熔断、轮换、拟人节奏 | 系统 |
| 04 | [采集与 API 服务解耦的聚合架构](./skills/web-scraping/04_aggregator_pipeline_design.md) | 抓取与供数分离：快照 + 只读 API + 多形态输出 | 架构 |
| 05 | [故障查表](./skills/web-scraping/05_failure_taxonomy.md) | 33 条症状 → 根因 → 动作。**最常用的一篇** | 排障 |
| 06 | [可运行代码模板](./skills/web-scraping/06_code_templates.md) | 12 个可直接跑的模板，从侦察到通知 | 实现 |
| 07 | [签名参数与加密参数逆向](./skills/web-scraping/07_js_signature_reverse.md) | 三条路线 + 六种定位手法 + 四步验证 | 高难 |
| 08 | [统一采集接口契约](./skills/web-scraping/08_unified_collection_contract.md) | 素材/情报双适配器共用的 manifest、去重、断点、限速、元数据契约（v1，2026-11 新增） | 架构 |

### 按情况查：我该读哪篇

| 你现在的情况 | 读 |
|---|---|
| 完全不知道从哪下手 | [SKILL.md](./SKILL.md) 第 1 节 |
| 403 / 503 / 验证码 / 被拦了 | [01](./skills/web-scraping/01_anti_scraping_sop.md) |
| 状态 200 但页面是空的 / `about:blank` | [02](./skills/web-scraping/02_cdp_detection_bypass.md) |
| 白屏，但请求头看着都正常 | [05](./skills/web-scraping/05_failure_taxonomy.md) F-13 |
| 要建一个能长期跑的系统 | [03](./skills/web-scraping/03_deep_site_scraper_engineering.md) |
| 多个数据源，要对外提供 API | [04](./skills/web-scraping/04_aggregator_pipeline_design.md) |
| 接口有 sign / token / 加密参数 | [07](./skills/web-scraping/07_js_signature_reverse.md) |
| 要落盘采集 / 写素材清单 / 情报入库 / 去重断点 | [08](./skills/web-scraping/08_unified_collection_contract.md) |
| 昨天能跑今天不行了 | [05](./skills/web-scraping/05_failure_taxonomy.md) F-24（三 diff 法） |
| 想直接抄代码 | [06](./skills/web-scraping/06_code_templates.md) |
| 数字是乱码 / 数据看着是假的 | [05](./skills/web-scraping/05_failure_taxonomy.md) D-15 / D-16 |

### 三条学习路径

**路径 A：快速上手（1 小时，能干活）**

```
SKILL.md §0 §1 P0-P2  →  06 的 T-01 侦察脚本  →  05 §0 黄金排查序列
```

**路径 B：系统补课（半天，能建系统）**

```
01 全文  →  02 全文  →  03 全文  →  06 T-03/T-05/T-06/T-07/T-08
```

**路径 C：攻硬骨头（按需）**

```
遇到 about:blank        → 02
遇到 sign/token          → 07
遇到 CF/Akamai/DataDome  → 01 §三 + 06 T-04
搞不定报错               → 05（先查表，别重读方法论）
```

---

## ② GitHub 热门技能收藏（repos/，2026-11-15 收录）

按 star 数排序。每个目录都是浅克隆（--depth 1），要更新就在目录里 `git pull`。

| 仓库 | Star | 技能入口 | 一句话 | 什么时候用它 |
|---|---|---|---|---|
| [claude-code-skill-scrapling](https://github.com/Cedriccmh/claude-code-skill-scrapling) | ⭐ 488 | `SKILL.md` | 基于 Scrapling 抓取，按站点特征自动选 Fetcher，抗 Cloudflare 类反爬 | **通用网页抓取首选**，中文文档 |
| [skilless.ai](https://github.com/BrikerMan/skilless.ai) | ⭐ 228 | `README.zh.md` | 给 Agent 真实数据能力：搜索 + 抓取 + 结构化提取工具集 | 要"搜+取"一体化的数据管道 |
| [WebReaper](https://github.com/alex-on-ai/WebReaper) | ⭐ 152 | `README.md` / `CLAUDE.md` | 单二进制 AI 爬虫，自带 Claude 技能，免配环境 | 快速起量、不想装 Python 环境 |
| [firecrawl/skills](https://github.com/firecrawl/skills) | ⭐ 152 | `skills/` 目录 | Firecrawl 官方技能目录：搜索、抓取、爬站、结构化 | 已有/愿意用 Firecrawl API 时 |
| [web-scraper](https://github.com/yfe404/web-scraper) | ⭐ 110 | `SKILL.md` | 智能策略选择：流量拦截 / sitemap / API / DOM，含 Apify Actor 开发 | 生产级采集、Apify 生态 |
| [media-crawler-easy](https://github.com/isheng-eqi/media-crawler-easy) | ⭐ 16 | `SKILL.md` | B站/小红书/抖音/快手/微博/贴吧/知乎 **7 平台评论采集**，扫码登录，出 HTML+CSV | 中文社媒舆情、评论分析（实用度远超 star） |
| [wechat-article-crawler](https://github.com/gxcsoccer/wechat-article-crawler) | ⭐ 13 | `SKILL.md` | 微信公众号文章 → 结构化数据 + Markdown，自动下载图片绕防盗链 | 公众号文章存档、内容聚合 |

### 怎么安装其中某个

```bash
# 方式一：npx 安装到 Claude Code / 兼容宿主
npx skills add <github仓库地址> --skill <技能名>

# 方式二：复制到 WorkBuddy 用户技能目录（推荐，本机已验证可行）
# 把仓库里的 SKILL.md（连同 references/、scripts/ 等）复制到：
#   C:\Users\26808\.workbuddy\skills\<技能名>\
```

装完在对话里说关键词即可触发（各技能的 `description` 里有触发词）。

---

## ③ 目录结构

```
D:\00_skiill_ku\01_crawler\
├── README.md                      ← 人类入口（本文件）
├── SKILL.md                       ← 模型入口（执行协议，library_root 已指向本目录）
├── skills\
│   └── web-scraping\              ← 自研协议库（8 篇 + YAML 索引）
├── repos\                         ← GitHub 热门技能收藏（浅克隆，可 git pull 更新）
│   ├── claude-code-skill-scrapling\   ⭐488
│   ├── skilless.ai\                   ⭐228
│   ├── WebReaper\                     ⭐152
│   ├── firecrawl-skills\              ⭐152
│   ├── web-scraper\                   ⭐110
│   ├── media-crawler-easy\            ⭐16（中文社媒，46MB）
│   └── wechat-article-crawler\        ⭐13（公众号）
└── （浏览器内核已迁移至 D:\00_skiill_ku\01_crawler\runtime\，由 PLAYWRIGHT_BROWSERS_PATH 指向；
     本库内不再保留 Camoufox\ / Playwright\ 目录，2026-11-17 审计确认）
```

> 历史备注：本库曾位于 `E:\00_Engineering_Skills`，SKILL.md 的 `library_root` 已同步修正为当前路径
> （`C:\Users\26808\.workbuddy\skills\web-scraping-playbook\SKILL.md` 里的同款路径也一并修了）。

---

## 怎么把库塞给模型

**方式一：直接贴入口** — 把 `SKILL.md` 作为系统提示或首个上下文，模型按路由表自己读需要的文件。

**方式二：按需加载（省 token）** — 只贴 `SKILL.md` + 当前任务对应的那 1~2 篇。

**方式三：作为 Skill 目录** — 已装好：`C:\Users\26808\.workbuddy\skills\web-scraping-playbook\`，对话中提到爬虫/反爬/采集即触发。

**给模型的三条使用提示**（可以一起贴）：

```
1. 先读 SKILL.md，按 §2 路由表只加载需要的文件，不要全读。
2. 严格按 P0→P5 推进，每阶段的"门禁"不过就退回上一阶段。
3. 交付必须含五段：定性结论 / 选型理由 / 可运行代码 / 验证命令与期望输出 / 风险。
```

---

## 新增技能的规范

### 1. 命名
`序号_英文短名.md`，按技术领域分目录（如 `web-scraping/`、`data-pipeline/`）。

### 2. 必须带 frontmatter

```yaml
---
id: WS-08                      # 领域缩写 + 序号
title: 文档标题
level: 通用 | 进阶 | 系统 | 架构 | 排障 | 实现 | 高难
phase: [P1, P3]                # 对应 SKILL.md 的哪个阶段
triggers: [关键词1, 关键词2]     # 用户怎么说会命中这篇
read_when: 什么情况下该读
skip_when: 什么情况下不该读（去读哪篇）
outputs: [产出物1, 产出物2]
next: [WS-06]
---
```

### 3. 正文结构

```
标题
> 一句话结论 + 所属阶段 + 前后文档
🎯 适用场景（含"不适用"）
<正文：表格 > 代码 > 分点>
⚠️ 避坑指南
```

### 4. 四条写作纪律

| 纪律 | 说明 |
|---|---|
| **结论前置** | 每节开头就说结论，不要铺垫 |
| **给数字，不给形容词** | 写"延迟 5~10 秒"，不写"适当延迟" |
| **可验证** | 每个方案配一个"怎么证明它生效"的检查 |
| **写清不适用** | 只写"什么时候用"的文档，模型会滥用 |

### 5. 更新索引
新增后同步改三处：`README.md` 表格、`00_index.md` 的 YAML、必要时 `SKILL.md` 的路由表。

---

## 本库的立场

1. **先定性再动手** —— 打错层是最贵的错误
2. **简单方案优先** —— 能 `curl_cffi` 就不上浏览器，能官方 API 就不逆向
3. **节奏优于指纹** —— 降频比任何 stealth 补丁都有效
4. **不接商业打码 / 付费代理** —— 优先开源方案 + 自建池
5. **合规是前提** —— 只抓有权访问的数据，控制频率，遵守服务条款

> 本库的所有参数（延迟秒数、阈值、TTL）都是**经验起点**，不是定理。落地时按目标站点实际响应调整，并做成可配置项。
