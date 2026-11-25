---
id: WS-08
title: 统一采集接口契约（素材 / 情报双适配器）
version: 1.0
level: 架构
phase: [P2, P3, P4]
triggers: [统一格式, manifest, 去重, 断点, 素材清单, 情报入库, 元数据, 速率限制]
use_when: 任何会落盘文件或写入情报库的采集任务；视频素材采集与 TechRadar 情报采集复用同一套底座时
skip_when: 一次性只读侦察且不落盘（走 P0 四连命令即可）
---

# WS-08 统一采集接口契约

> 代码实现：`D:\00_skiill_ku\_shared\skillkit\manifest.py`（清单与去重）、`policy.py`（超时/重试/限速/断点）。
> 本文档是协议，代码是可执行实现；两者冲突以代码为准并回改本文档。

## 1. 两类适配器，一套底座

| 适配器 | 服务对象 | 典型来源 | 产出 |
|---|---|---|---|
| `material` | 视频/图文生产 | Pexels/Pixabay、合规网页、用户提供链接 | 本地媒体文件 + `assets_manifest.json` |
| `intel` | TechRadar 情报 | Folo/Reddit/HN/GitHub/博客 | SQLite entries + 证据链接 |

共用能力（不许各写一套）：HTTP 会话与 UA、下载落盘、MIME 嗅探、SHA256、去重、目录规范、脱敏日志、重试退避、限速、断点。

## 2. 统一记录字段（collection-manifest-v1）

每条记录必须包含：

| 字段 | 含义 | 约束 |
|---|---|---|
| `source_url` | 原始 URL | 主键之一，禁止编造 |
| `title` | 标题 | 取不到写 `untitled` |
| `media_type` | webpage/article/image/video/audio/subtitle/repo/post | 枚举外取值直接报错 |
| `collected_at` | 采集时间 | ISO8601，自动生成 |
| `published_at` | 发布时间 | 取不到写 `null`，不许猜 |
| `source_name` | 来源名 | 如 `pexels`、`r/coolgithubprojects` |
| `file_path` | 本地落盘路径 | 未下载为 `null` |
| `sha256` | 文件哈希 | 落盘后必填 |
| `license_status` | 许可 | **默认 `unknown`，禁止默认可商用**；枚举 unknown/licensed/public-domain/cc-*/forbidden |
| `http_status` | 响应码 | 失败也记录 |
| `adapter` | material / intel | |
| `status` | discovered/downloaded/verified/failed/skipped | |
| `extra` | 扩展字段 | 时长、分辨率、帧率、互动指标等放这里 |

## 3. 强制策略（policy.CrawlPolicy 默认值）

- 超时 30s；最大重试 3 次（不含首次）；指数退避 2s 起、上限 30s，加 0–0.8s 抖动。
- 同域请求最小间隔 1.5s；429/403 触发退避并按 `05_failure_taxonomy.md` 定性，禁止循环硬闯。
- 断点：`Checkpoint` 把已完成 URL 持久化到 JSON，重跑先读断点，已完成的跳过。
- 认证类失败（401/403 token 类）不重试、不猜凭据，直接 BLOCKED。
- 单任务连续两轮修复仍失败 → 停该分支，标 FAIL/BLOCKED，继续其他任务。

## 4. 去重规则（两级）

1. URL 级：`source_url` 命中 → `dup_url`，不重复下载。
2. 内容级：落盘后 SHA256 命中已有记录 → `dup_hash`，保留首次记录，重复文件删除或移入 `_dupes/`，不许静默覆盖。

情报适配器的 URL 去重同时写入 SQLite `entries.content_hash` 唯一索引（见 06_techradar 模块）。

## 5. 媒体验证门禁（material 适配器）

下载后必须全部通过才允许 `verified`：

1. 文件大小 > 0 且 MIME 与扩展名一致；
2. 图片：Pillow 能打开并读出尺寸；
3. 视频/音频：`ffprobe` 能读出容器与流信息（时长、分辨率、帧率、音轨）；
4. 重算 SHA256 与清单一致；
5. 任一项失败 → `failed` 并在日志写明验证项，不得把网页缩略图当原视频。

## 6. 目录与文件规范

```
<project_root>/
├── inputs/<yyyyMMdd_HHmmss>/     # 原始下载
├── work/                         # 中间产物
├── outputs/                      # 成品
├── assets_manifest.json          # material 清单
└── .crawl_checkpoint.json        # 断点
```

文件名清洗：只保留中文、字母、数字、下划线、短横线、点；长度 ≤ 80；冲突时追加 `_<hash前8位>`。

## 7. 失败分类与出口

| 现象 | 出口 |
|---|---|
| 超时 / 5xx / 连接重置 | 退避重试，耗尽后 failed 并保留 http_status |
| 401 / token 失效 | BLOCKED: AUTH_REQUIRED，不重试 |
| 403 / 429 / 验证码 / CDP 检测 | 转 `01/02/05` 文档，禁止裸请求死磕 |
| 登录墙 / 付费墙 | 停止，记录 NEEDS_USER_APPROVAL |
| 许可未知 | license_status=unknown，可入清单但禁止进正式作品 |

## 8. 最小调用示例

```python
from skillkit.manifest import CollectionManifest, CollectionRecord
from skillkit.policy import CrawlPolicy, RateLimiter

policy = CrawlPolicy()
limiter = RateLimiter(policy)
manifest = CollectionManifest(project="demo")
limiter.wait("example.com")
rec = CollectionRecord(source_url="https://example.com/a.jpg", title="a",
                       media_type="image", source_name="example", adapter="material")
# ... requests 下载到本地后 ...
rec.attach_file("inputs/20261117_demo/a.jpg")
print(manifest.add(rec))   # inserted / dup_url / dup_hash
manifest.save("assets_manifest.json")
```
