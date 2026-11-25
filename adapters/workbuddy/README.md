# WorkBuddy 适配说明（部分已验证：本机存在 ~/.workbuddy/skills）

## 技能发现（已验证目录存在）
- 技能目录：`C:\Users\<user>\.workbuddy\skills\<name>\SKILL.md`。
- 本机已装：web-scraping-playbook、jobradar、windows-camera-diag、disk-cleanup-brain、frontend-design。
- 迁移方式：把库内 canonical 技能复制为同名目录；注意 SKILL frontmatter 内的绝对路径（如 library_root）按本机改写。

## MCP / 规则
- MCP 配置入口与格式以 WorkBuddy 当前版本文档为准（标记：待实测，不在无人值守中改活动配置）。
- 自定义规则区粘贴根 AGENTS.md 的「硬指令」段落与技能路由表。

## 平替要点
- 无 Trae 插件市场：飞书走 generic-agent/feishu-minimal.md；办公文档走 Python 库；发布走 aitoearn remote MCP（若客户端支持 HTTP MCP）。
- 浏览器运行时复用同一环境变量 PLAYWRIGHT_BROWSERS_PATH，无需重复下载 3GB 内核。
