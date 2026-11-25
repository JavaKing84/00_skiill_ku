# Loomi 适配说明（基于通用 Agent 机制，待实测）

> 状态标记：Loomi 无本机安装实例，以下为通用客户端模式推断，落地时需逐项实测，不得当作已验证事实。

## 技能发现
- 若无自动技能扫描：在系统提示/项目说明中写入「技能库根路径 + 场景→SKILL.md 映射表」，并明确要求命中场景先 Read 文件再执行。
- 映射表直接复制根 AGENTS.md §2 能力契约表的能力 ID 与文件路径。

## MCP
- 若支持 stdio MCP：按 `npx -y folo-mcp` / `npx -y reddit-mcp-buddy` 形式注册，凭证走环境变量。
- 若仅支持 HTTP MCP：aitoearn-cn 可直接挂；folo/reddit 需找社区 HTTP 桥或退到 Playwright 降级链。

## 规则文件
- 单份 system prompt 预算有限：只放路由表与红线，长协议保留在库内按需 Read（参照 WS 索引的 triggers 设计）。
