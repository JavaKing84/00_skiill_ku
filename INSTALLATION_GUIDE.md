# INSTALLATION_GUIDE.md — 安装与跨客户端迁移指南

适用：把 `D:\00_skiill_ku` 的能力在一台新机器 / 一个新 AI 客户端上重建。
原则：能力优先于产品名；先隔离安装；不动活动全局配置；每步有验收。

## 1. 运行时（系统级，人工安装）

| 组件 | 本机版本（实测 2026-11-17） | 验证命令 |
|---|---|---|
| Python | 3.14.7 | `python --version` |
| Node.js | 24.21.0 | `node -v` |
| Git | 2.54 | `git --version` |
| FFmpeg | 9.0.2（需含 ffprobe，PATH 可用） | `ffmpeg -version` |
| Playwright 浏览器内核 | 由 `PLAYWRIGHT_BROWSERS_PATH` 指向（本机 D:\00_skiill_ku\01_crawler\runtime\Playwright） | `python -m playwright --version` |

## 2. Python 依赖（项目级隔离）

新机器推荐：

```powershell
cd D:\00_skiill_ku
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`requirements.txt` 按本机实测版本固定（见同目录）。若离线无法建 venv，可临时用全局解释器（本机全局已含全部依赖），并在报告标注降级原因。

## 3. 库结构复制（无专有格式）

整个 `D:\00_skiill_ku` 复制即可；`01_crawler\runtime\`（Playwright + Camoufox，约 3.8 GB）可单独拷，
也可在新机用 `python -m playwright install chromium` 重建后把 `PLAYWRIGHT_BROWSERS_PATH` 指过去。
`repos/` 是 git 仓库，目标机用 `git -C <repo> rev-parse HEAD` 核对 commit，
与 `_reports/inventory.json` 的 git_repos 对照。

## 4. MCP 注册（只生成候选，不自动覆盖活动配置）

### 4.1 stdio 类（folo / reddit）
```json
"folo": { "command": "npx", "args": ["-y", "folo-mcp"], "env": { "FOLO_SESSION_TOKEN": "<人工填入>" } }
```
### 4.2 HTTP 类（aitoearn）
```json
"aitoearn-cn": { "url": "https://aitoearn.cn/api/ai/agent/mcp", "headers": { "X-Api-Key": "<人工填入>" } }
```
应用方式：先备份活动 mcp.json → 合并候选 → 重启客户端 → 用 VERIFICATION_RULES.md 的用例验收。
cn 站与 ai 站密钥不通用。

## 5. 凭证清单（人工配置，禁止写入仓库/日志/报告）

| 变量 | 用途 | 缺失影响 |
|---|---|---|
| FOLO_SESSION_TOKEN | Folo 订阅 | C07 BLOCKED |
| REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET | Reddit 社区 | C08 BLOCKED |
| X-Api-Key（aitoearn cn/ai） | 发布与云剪辑 | C06 正式发布不可用，dry-run 不受影响 |
| YOUDAONOTE_API_KEY | 云笔记 | C10 不可用 |
| FEISHU_APP_ID / FEISHU_APP_SECRET | 飞书平替 | C11 不可用 |

## 6. 迁移流程（对新客户端）

识别客户端 → 读 `adapters/<client>/README.md` → 对照 `CAPABILITY_REGISTRY.yaml` 查缺口
→ 按 alternatives 找平替 → 生成候选配置（不覆盖）→ 隔离测试 → 输出迁移报告并更新注册表状态。

## 7. 卸载/回滚

- 新增 Python 依赖：删除 `.venv` 即完全卸载，系统全局未改动。
- 文件级变更：按 `_backup\20261121_refactor\` 的迁移前快照与 `MOVE_MANIFEST.csv` 还原。
- 目录改名回滚：按 `MOVE_MANIFEST.csv` 的 `new_path` → `old_path` 反向移动即可。
