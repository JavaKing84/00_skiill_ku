# _shared — 共享服务包（skillkit）

爬虫、视频、TechRadar 三条链路共用的底座，纯标准库实现（requests/PIL 为可选增强）。

| 模块 | 职责 | 主要使用者 |
|---|---|---|
| `hashing.py` | 文件 SHA256、按哈希分组去重 | manifest / 测试 |
| `manifest.py` | collection-manifest-v1 清单、URL+哈希两级去重、落盘重载校验 | verify_asset、WS-08 |
| `policy.py` | 超时/重试退避/同域限速/断点 JSON | 全部采集脚本 |
| `loggingx.py` | 脱敏日志（token/key/cookie/Bearer 自动打码） | 全部脚本 |
| `media.py` | ffprobe 摘要、scene cut、blackdetect、volumedetect、抽帧 | 视频分析与 QC |
| `inteldb.py` | SQLite 情报库 8 张表、content_hash 唯一去重、分析台账 | TechRadar |
| `scripts/build_inventory.py` | 全库 inventory.json 生成 | 审计 |

测试：`python ../tests/test_skillkit_contract.py`（全局解释器与 `.venv` 均已验证 PASS）。
变更规则：契约字段升级必须升 `schema_version` 并同步 `01_crawler/skills/web-scraping/08`。
