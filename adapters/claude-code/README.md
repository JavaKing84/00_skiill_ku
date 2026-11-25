# Claude Code 适配说明（基于官方 CLI 公开机制，待本机实测）

## 技能发现
- 项目根 `CLAUDE.md` 作为入口：写库路径、能力路由表、红线；细节技能仍放库内 SKILL.md，用 Read 按需加载。
- 建议把 `D:\00_skiill_ku` 作为仓库的一部分或软链接入，使用相对路径，避免绝对盘符耦合。

## MCP（官方命令形式，落地时实测）
```bash
claude mcp add aitoearn-cn --transport http https://aitoearn.cn/api/ai/agent/mcp --header "X-Api-Key: $AITOEARN_KEY"
claude mcp add folo -- npx -y folo-mcp
claude mcp add reddit -- npx -y reddit-mcp-buddy
```
- 凭证一律走环境变量，不写进命令历史/文件；先 `claude mcp list` 核对再联调。

## 测试
- 本库 tests/ 为纯 Python/pytest 风格断言，可直接 `python tests/xxx.py` 运行，不依赖 Claude Code 专有功能。
