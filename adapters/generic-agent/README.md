# 通用 MCP Agent 适配说明（兜底，无插件假设）

## 最小假设
目标客户端至少具备：① 文件读写；② 终端执行；③ 可注入系统提示；④（最好）支持 stdio 或 HTTP MCP。

## 五步迁移
1. 复制 `D:\00_skiill_ku` 整个库（Markdown 技能 + Python 脚本，无专有格式）。
2. 系统提示写入根 AGENTS.md §0 的 10 条硬指令 + 技能路由表。
3. 装运行时：python 3.11+、node LTS、ffmpeg；Python 包 requirements 见 INSTALLATION_GUIDE.md。
4. 能挂 MCP 就挂；挂不了的能力按 CAPABILITY_REGISTRY.yaml 的 alternatives 降级。
5. 跑 tests/ 全量脚本，按 VERIFICATION_RULES.md 记录 PASS/PARTIAL/BLOCKED。

## 无 MCP 时的能力兜底
| 能力 | 兜底 |
|---|---|
| 素材采集/爬虫 | 本库 Python 脚本 + Playwright（WS-01~08） |
| 情报采集 | collect_public.py（HN/GitHub 公开 API）+ SQLite |
| 视频全链路 | ffmpeg + 03_video 四脚本 |
| 发布 | 只出 dry-run 预览，人工到平台后台发布 |
| 飞书 | 见 feishu-minimal.md |
| 笔记 | 本地 Markdown + git 版本化 |
