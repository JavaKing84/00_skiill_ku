# 💼 求职技能库 — job_radar

> 位置：`D:\00_skiill_ku\02_jobsearch`　|　总览见 [../README.md](../README.md)
> 最近整理：2026-11-15

本目录收录 **job_radar**（给 AI 助手的求职搜索技能：中国校招、实习、社招与招聘日历，自然语言提问，获取岗位要求、来源链接与投递入口）。

## 目录结构

```
D:\00_skiill_ku\02_jobsearch\
├── README.md                        ← 本文件
├── job_radar\                       ← GitHub 源仓库（浅克隆，2026-11-15 @ 2.3.6）
└── workbuddy-skill-jobradar\        ← 已安装到 WorkBuddy 的技能壳副本
    ├── SKILL.md                     ← 技能入口（含本机安装位置说明）
    └── references\                  ← 候选流程 / 字段说明 / 示例 / 配置
        ├── candidate-workflow.md
        ├── examples.md
        ├── fields.md
        └── setup.md
```

## 三者的关系（重要）

| 角色 | 位置 | 说明 |
|---|---|---|
| **源仓库** | 本目录 `job_radar\` | GitHub 项目源码，用来读文档、看更新、提 issue |
| **技能壳** | 本目录 `workbuddy-skill-jobradar\` | 已安装技能的副本，WorkBuddy 对话中触发求职查询时加载的就是它 |
| **运行时** | `D:\新建文件夹 (2)\jobradar\` ⚠️ | **真正的可执行程序**：`.venv\Scripts\jobradar.exe`（v2.3.6）+ `_repo\` + 数据目录 |

> ⚠️ **不要搬运行时目录**。`D:\新建文件夹 (2)\jobradar\.venv` 是独立虚拟环境，路径写死在技能壳的
> SKILL.md 里，搬走后技能会失效。要迁移的话：搬完同步改 SKILL.md 里的路径。

## 快速用法

```bash
# 查实习岗位（本机调用方式，绝对路径）
"D:/新建文件夹 (2)/jobradar/.venv/Scripts/jobradar" search --type intern --city 上海 --category 产品经理

# 其他常用
jobradar search --type campus --city 北京          # 校招
jobradar calendar                                  # 招聘日历
jobradar doctor                                    # 体检（数据源连通性）
```

对话中直接说也行：**"上海有没有产品经理实习在招"** "字节这周新开了什么岗" "A 公司和 B 公司的算法岗要求差异"。

## 浏览器插件协作（2026-11-21 实测盘点）

- 用户 Chrome 已装 **boss-helper**（BOSS直聘辅助插件）：jobradar 管数据与检索，boss-helper 管网页端人工投递交互，两者互补。需要用户在 BOSS 直聘网页上操作时，明确告知"这一步用你装好的 boss-helper 完成"。
- jobradar 体检结果（2026-11-21 doctor 实测）：jobs.db 333MB / jd_text.db 232MB / calendar.db 9.9MB，1655 目标公司日历覆盖 1275，JD 覆盖 1082，数据健康；`grad_year` 字段填充率仅 9.6%，按年级过滤时需意识到此局限。

## 数据与维护

- 数据目录：`~/.cache/jobradar`（三库已下载，约 559MB）
- 数据每日调度更新，单源新鲜度以返回时间为准
- GitHub：https://github.com/lijiaqi-AI-Product-Manager/job_radar
- 更新源仓库：在 `job_radar\` 目录里 `git pull`；升级运行时按仓库 README 的安装文档走
