# 01_crawler 脚本参数参考（由 scripts/*.py 自动提取）

> 本文件由脚本的 argparse 定义自动生成，**以代码为准**。
> 生成时间：2026-11-24。修改脚本参数后请重新生成本文件，避免文档与实现漂移。

## `build_platform_matrix.py`

build_platform_matrix.py — 汇总 probe_site / probe_logged_in 结果，生成平台兼容矩阵。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--in-dir` |  |  |

## `extract_article.py`

extract_article.py — 正文抽取（可降级三引擎）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--url` |  |  |
| `--file` |  |  |
| `--engine` |  | 可选值: auto / trafilatura / readability / builtin；默认: `auto` |
| `--out` |  |  |
| `--json` |  |  |

## `probe_logged_in.py`

probe_logged_in.py — 使用用户本机已登录的浏览器配置做**授权范围内**的可访问性探测。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--site` |  | 必填 |
| `--profile` |  | 必填 |
| `--headless` |  | 开关 |
| `--out` |  |  |

## `probe_site.py`

probe_site.py — 网站公开可访问性与数据结构探测（P0 情报层的可执行实现）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--url` |  | 必填 |
| `--api` | 按 JSON 接口探测 | 开关 |
| `--out` |  |  |
