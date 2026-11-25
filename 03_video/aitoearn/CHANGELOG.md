# Changelog

## 0.0.6

### 变更

- 新增子技能 `material-sourcing`（找素材）：按主题检索免费可商用图片/视频，在对话内展示预览、规格与授权，按用户指令筛选后用 `sync_materials` 存入 Studio 工程素材库；支持另存媒体库。
- 新增 `scripts/stock-search.mjs`：图片走 Openverse（CC0 / CC BY，支持竖屏过滤），视频走 Mixkit 分类页并解析 mp4 直链；输出统一 JSON（标题、直链、尺寸、时长、授权、来源页）。
- 入口 SKILL.md 路由与关键词补充「找素材 / 搜图片 / 搜视频 / 素材库」。

### 验证

- `node scripts/stock-search.mjs --type all --q "night city"`：图片命中 Wikimedia 直链 ✓；视频命中 Mixkit 1080×1920 直链 ✓。
- 外部直链可用性：Mixkit 720/1080 mp4 HEAD 200 ✓；Openverse 匿名检索 200 ✓。
- 全流程回归：找素材 → 建工程 → sync_materials 4/4 → 14s 竖屏时间线 → 1080p 导出 → 抖音发布预约 → 取消 ✓。
- 发现并修复：抖音拒绝导出域名（`disallowed_domain`）；`channel-publish` 增加「先转存到 assets.aitoearn.cn 再发布」规则。
- 发现并规避：Wikimedia / StockSnap 直链防盗链导致图片探测 500，检索脚本默认跳过。

## 0.0.5

### 变更

- 新增 `scripts/aitoearn-mcp-setup.mjs`：交互式 Key 配置。写入 `~/.aitoearn/config.json`（chmod 600）+ 注册 Trae 用户级 `~/.trae-cn/mcp.json`（合并保留已有服务器）+ 实测 `tools/list` 验证，支持 `cn` / `ai` 双站。
- 入口技能 SKILL.md 新增 onboarding 路由：会话缺少 aitoearn 工具或调用返回 `-32001` 时，助手主动向用户询问 API Key 并执行上述脚本，成功后引导重载 MCP；全程不回显 Key。
- README「MCP 鉴权」新增交互式配置章节（推荐路径），原桥接手动配置降级为备选。

### 验证

- 真实端点 `https://aitoearn.cn/api/ai/agent/mcp`：连通 ✓；匿名会话仅暴露 `aitoearn_connection_help` ✓（与文档一致）。
- 脚本合并行为经 `AITOEARN_CONFIG` / `AITOEARN_MCP_CONFIG` 重定向测试：保留已有服务器 ✓、污染隔离 ✓。

## 0.0.4

从 WorkBuddy 专家包 `aitoearn-workbuddy-0.0.4` 复制并按 Agent Plugins 1.0.0 重新打包，技能内容与功能不变。

### 变更

- `agents/aitoearn.md` → `skills/aitoearn-orchestrator/SKILL.md`（规范无 agent 组件，降级为靠 description 触发的入口技能）。
- `.codebuddy-plugin/plugin.json` → 根 `plugin.json`，仅保留 10 个标准字段；displayName / profession / avatar / tags / quickPrompts / dependencies 等私有字段移除。
- `.mcp.json` → 根 `mcp.json`，`type: http` → `stdio`；新增 `scripts/aitoearn-bridge.mjs` 在运行时注入 Bearer 鉴权（规范的 mcp.json 不展开 `${VAR}`，且不接受私有 `x-workbuddy` 字段）。
- 新增 `scripts/validate.mjs`（规范自检）、`scripts/pack.mjs`（插件包 + 单技能双产物）、`scripts/selftest.mjs`（桥接端到端，9/9）、`scripts/rename.mjs`（换品牌）。
- 入口技能补充客户端可移植性说明：`guide_*` 信号工具在当前客户端不渲染时，改为在回复正文写出指引。

### 验证

- `node scripts/validate.mjs` → 0 error / 1 warning（license 未定）
- `node scripts/selftest.mjs` → 9/9
- 未验证：真实 aitoearn 端点的 `tools/list`
