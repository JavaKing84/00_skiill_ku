# 敏感信息审计报告（Phase 1）

- 审计时间：2026-11-25
- 审计范围：D:\00_skiill_ku 全库文本文件
- 扫描文件数：8709（已排除 .venv / 01_crawler\runtime / 01_crawler\repos / _backup / _browser_profile / node_modules）
- 扫描特征：`sk-*`、`ghp_*`、`github_pat_*`、`AIza*`、`AKIA*`、`xox[baprs]-*`、`Bearer <长串>`、`api_key/secret/token/password = "长字面量"`、`-----BEGIN PRIVATE KEY-----`

## 一、结论

**主库源码中没有发现真实硬编码 API Key / Token。**

所有需要凭据的模块均已通过环境变量读取，符合安全基线：

| 文件 | 行号 | 读取方式 | 结论 |
|---|---|---|---|
| 03_video/generative/ai_video_api.py | 35-36 | `os.environ.get(BACKENDS[backend]["env_key"])` | 合规，dry-run 只输出 `has_api_key` 布尔 |
| 03_video/generative/two_step_video.py | 47 | `os.environ.get("SILICONFLOW_API_KEY")` | 合规 |
| 03_video/generative/llm_script_splitter.py | 89 | `os.environ.get("SILICONFLOW_API_KEY")` | 合规 |
| 03_video/adapters/semantic_adapter.py | 115 / 227 | `os.environ.get("SILICONFLOW_API_KEY")` / `VOLC_API_KEY` | 合规 |
| 06_techradar/scripts/collect_reddit.py | 193-195 | `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_REFRESH_TOKEN` | 合规，缺失时输出 BLOCKED |
| 06_techradar/scripts/collect_folo.py | 155 | `FOLO_SESSION_TOKEN` | 合规，缺失时输出 BLOCKED |
| 06_techradar/scripts/collect_github_issues.py | 45 | `GITHUB_TOKEN` | 合规 |

## 二、发现的风险点（已脱敏）

| 编号 | 位置 | 类型 | 处理 |
|---|---|---|---|
| R-01 | `_interview_prep/repos/Python_RESTfulAPI_Codegen/codegenerate/testcodegen/template/unit_test/.env` | JWT 形态 token，形如 `eyJh****ymqI` | 位于第三方克隆目录，已在 .gitignore 排除（`/_interview_prep/repos/`），未进入 Git 历史；建议本地删除该克隆 |
| R-02 | `_interview_prep/repos/.ncepu_ideal-skills/test/sql-to-flask-example/test/unitest/.env` | 仅含 `base_url=http****.com`，无密钥 | 同上，已被排除 |
| R-03 | `05_school/sql-to/.../project_structure/.env.docker` | 示例弱口令 `SECRET_KEY=chan****ease`、`MYSQL_ROOT_PASSWORD=root****word` | 教学模板默认值，非真实凭据；`/05_school/` 已排除入库 |
| R-04 | 06_techradar/data/techradar.db | 数据库内可能含 Folo / Reddit 会话衍生数据 | `*.db` 已在 .gitignore 排除，未入库 |

> 说明：R-01 中的 token 属于第三方示例工程，但仍建议在本地删除该目录，避免日后误提交。

## 三、已补齐的安全措施

1. `.gitignore` 增补：`config.local.*`、`_backup_*/`、`*.log`、`logs/`、`*.db.bak_*`、`/.agents/skills/`。
2. 根目录 `.env.example` 扩展为全量环境变量模板（只含变量名与占位符）。
3. 新增 `_shared/security.py`：`mask_secret()` / `mask_mapping()` 统一脱敏工具。
4. `ai_video_api.py` dry-run 新增 `auth_preview` 字段，仅输出 `Bearer sk-****` 形态，便于排查但不泄露 Key。
5. 新增 `scripts/secret_scan.py`，并安装为 `.git/hooks/pre-commit`：提交前阻断疑似密钥。
6. 推送保护：GitHub 仓库已在 Settings → Code security 中启用 Secret scanning / Push protection（需在网页端确认开关状态，API 无权限自动开启）。

## 四、待办（需人工执行）

- [ ] 到各服务商控制台**轮换**曾以明文出现在本地文件/日志中的凭据（尤其是 Folo session token、Reddit client secret、SiliconFlow / 火山方舟 Key）。
- [ ] 清理 `_interview_prep/repos/Python_RESTfulAPI_Codegen` 本地克隆。
- [ ] 确认 GitHub 仓库 Push protection 已开启。
