# VERIFICATION_RULES.md — 验收定义与质量门禁

## 1. 状态语义（不得越级标记）

`DISCOVERED`（发现未配置）→ `CONFIGURED`（有配置未证明连接）→ `CONNECTED`（能连接未证明业务）
→ `PASS`（真实业务测试通过）。旁路状态：`PARTIAL / BLOCKED / FAIL / NOT_TESTED / DEPRECATED`。

## 2. PASS 五条件（全部满足）

1. 命令/工具真实执行并记录退出码；
2. 输出文件或数据真实存在（给路径与大小/哈希）；
3. 核心字段或媒体可被解析；
4. 结果符合明确预期；
5. 日志/证据可复查（存于 `_logs/` 或 `_reports/`）。

只有语法检查、只有工具列表、只有配置文件 → 最多 CONFIGURED，禁止标 PASS。

## 3. 测试矩阵与最低用例

| 套件 | 脚本 | 关键断言 | 证据 |
|---|---|---|---|
| 契约/去重/脱敏 | tests/test_skillkit_contract.py | 两级去重、断点、掩码、清单枚举校验 | 退出码+stdout |
| 视频流水线 | tests/test_video_pipeline.py | 合成视频→分析→QC→dry-run 全链路；QC 能抓出无声失败 | 生成文件+QC verdict |
| 情报库 | tests/test_techradar.py | 建表、重复采集 duplicate、读取状态机、run 台账 | SQLite 行数 |
| 迁移注册表 | tests/test_registry.py | YAML 可解析、必填字段齐全、状态枚举合法 | 解析结果 |
| 端到端采集 | verify_asset.py 对 1 个公开小文件 | 下载+验证+manifest 登记 | manifest 记录 |

## 4. 测试数据规则

- 媒体 fixture 一律用 ffmpeg `lavfi` 本地合成，不下载版权素材。
- 网络用例只打公开、免登录、低频接口；失败按 BLOCKED 记录，不循环重试。
- 发布测试只允许 dry-run；断言产物中不含任何真实发布调用。

## 5. 修复规则

普通失败最多 2 轮有明确改动的修复；认证失败不重试不猜密钥；两轮不过转 FAIL/BLOCKED 并继续其他工作。

## 6. 证据归档

每个测试 run 在 `_logs/<timestamp>/` 保存命令、退出码、关键输出；总结写入 `_reports/TEST_REPORT.md`。
