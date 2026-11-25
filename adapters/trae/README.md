# Trae 适配说明（已验证：本机实测）

## 技能发现
- 目录扫描：`C:\Users\<user>\.trae-cn\skills\<name>\SKILL.md`，按 frontmatter 的 `name`/`description` 自动触发。
- 用户级规则：`~\.trae-cn\user_rules\*.md`，`alwaysApply: true` 的规则每条会话注入。
- 库内 canonical 技能（`D:\00_skiill_ku\03_video` 等）不在扫描目录时，靠根 `AGENTS.md` + 规则中的显式路径 Read 触发。

## MCP 配置
- 文件：`~\.trae-cn\mcp.json`，键 `mcpServers`。
- 支持 stdio（command/args/env）与 HTTP（url/headers）两种；本机 4 个服务器均已注册。
- 禁令：无人值守不得修改该活动文件；变更只能生成候选片段 + 备份说明。

## 插件
- 插件市场提供 lark / github / office / deployment 等，能力随插件安装出现；插件不可拷出本生态，迁移时查 CAPABILITY_REGISTRY 的 alternatives。

## 本机实测证据
- folo MCP 调用返回缺 session token；reddit MCP 返回匿名 RSS 终止（2026-11-17，见 _reports/AUDIT_REPORT.md §3）。
- ffmpeg/python/node 均在 PATH，版本见审计报告 §1。
