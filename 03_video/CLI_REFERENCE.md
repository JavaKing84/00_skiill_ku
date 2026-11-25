# 03_video 脚本参数参考（由 scripts/*.py 自动提取）

> 本文件由脚本的 argparse 定义自动生成，**以代码为准**。
> 生成时间：2026-11-24。修改脚本参数后请重新生成本文件，避免文档与实现漂移。

## `audio_skill.py`

audio_skill.py — 把混音逻辑封装成可调用函数，避免每次手写超长 filter_complex。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--voice` |  | 必填 |
| `--bgm` |  |  |
| `--speech` | 台词窗口，如 22.55-24.35,30-33 |  |
| `--out` |  | 默认: `audio_diagnose.json` |

## `edl_io.py`

edl_io.py — 内部时间轴 JSON ↔ CMX3600 EDL 最小读写（零第三方依赖）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--timeline` |  |  |
| `--read` |  |  |
| `--fps` |  |  |
| `--out` |  | 必填 |

## `material_retrieve.py`

material_retrieve.py — 多模态素材条件检索（复用前置分析结果，不解码视频、不建向量库）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--shots` |  | 必填 |
| `--person-csv` |  |  |
| `--person-detail` |  |  |
| `--whisper` |  | 默认: `[]` |
| `--source` |  |  |
| `--person` |  |  |
| `--exclude` |  |  |
| `--scale` |  |  |
| `--long-shot` |  | 开关 |
| `--short-shot` |  |  |
| `--dialogue` |  |  |
| `--min-dur` |  |  |
| `--max-dur` |  |  |
| `--avoid-json` | 黑名单/禁支线窗口 JSON（配合 --avoid-buffer 物理避让） |  |
| `--avoid-buffer` | 敏感人物避让缓冲秒数（前后各 N 秒，默认 5） | 默认: `5.0` |
| `--no-fallback` | 关闭 0 命中自动降级（默认开启：降级为 empty_shot_with_vo） | 开关 |
| `--out` |  | 默认: `material_retrieve_result.csv` |

## `montage_edit.py`

montage_edit.py — 基于 EDL 的确定性混剪渲染器（可复现，不做黑箱）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--edl` |  | 必填 |
| `--out` |  | 必填 |
| `--work` |  |  |

## `person_scan.py`

person_scan.py — 画面人物检索/筛选（纯 CPU，ONNXRuntime-YuNet + OpenCV-SFace）

| 参数 | 说明 | 备注 |
|---|---|---|
| `--video` |  |  |
| `--start` |  |  |
| `--end` |  | 默认: `60.0` |
| `--gallery` |  | 默认: `D:\00_skiill_ku\03_video\assets\elephant\faces` |
| `--window` |  | 默认: `4.0` |
| `--fps` |  | 默认: `1.0` |
| `--min-score` |  | 默认: `0.7` |
| `--min-face` |  | 默认: `48` |
| `--sim-threshold` |  |  |
| `--frame-width` |  | 默认: `960` |
| `--out` |  | 默认: `person_scan_result.csv` |
| `--detail-json` |  |  |
| `--build-gallery` |  | 开关 |
| `--spec` |  |  |
| `--video-dir` |  | 默认: `D:\00_skiill_ku\03_video\assets\elephant\raw` |

## `publish_preview.py`

publish_preview.py — 发布 dry-run 预览（Phase 2.5）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--video` |  | 必填 |
| `--platform` | 如 douyin/xiaohongshu/bilibili | 必填 |
| `--account` |  |  |
| `--title` |  | 必填 |
| `--description` |  |  |
| `--tags` | 逗号分隔 |  |
| `--cover` |  |  |
| `--scheduled-at` |  |  |
| `--out` |  | 必填 |

## `quality_check_all.py`

quality_check_all.py — 成片质量综合巡检统一入口（纯分析，绝不渲染 mp4）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--timeline` |  | 必填 |
| `--video-dir` |  | 默认: `D:\00_skiill_ku\03_video\assets\elephant\raw` |
| `--gallery` |  | 默认: `D:\00_skiill_ku\03_video\assets\elephant\faces` |
| `--forbidden` | 禁止支线 JSON 路径 |  |
| `--emotion-script` |  |  |
| `--allow-jcut` |  | 开关 |
| `--no-allow-jcut` |  |  |
| `--blacklist-level` |  | 可选值: block / warn；默认: `block` |
| `--blacklist-buffer` | 敏感人物/禁支线窗口前后避让缓冲秒数（默认 5） | 默认: `5.0` |
| `--bgm` |  |  |
| `--outdir` |  | 默认: `demo_out` |
| `--skip-person` |  | 开关 |
| `--skip-shot` |  | 开关 |

## `reference_analyze.py`

reference_analyze.py — 参考视频逆向分析（Phase 2.2）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--video` |  | 必填 |
| `--out` |  | 必填 |
| `--scene-threshold` |  | 默认: `0.35` |

## `render.py`

render.py — 03_video 最小渲染脚本（跨客户端可复现）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--inputs` | 输入视频（按顺序拼接） | 必填 |
| `--out` |  | 必填 |
| `--aspect` |  | 默认: `16:9` |
| `--subtitle` | 字幕文本（单条，底部） |  |
| `--bgm` | BGM 路径（必须在授权登记表内） |  |
| `--bgm-gain-db` |  | 默认: `-18.0` |
| `--fps` |  | 默认: `30` |
| `--qc` | 渲染后自动执行 video_qc.py | 开关 |

## `shot_analyze.py`

shot_analyze.py — 镜头语义解析（景别 / 运动量 / 长短镜头），纯 CPU。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--video` |  | 必填 |
| `--start` |  |  |
| `--end` |  | 默认: `60.0` |
| `--threshold` |  | 默认: `27.0` |
| `--min-len` |  | 默认: `0.4` |
| `--sample-fps` |  | 默认: `2.0` |
| `--long-shot-sec` |  |  |
| `--out` |  | 默认: `shot_analyze_result.json` |
| `--frames` |  |  |

## `shot_detect.py`

shot_detect.py — 镜头边界检测（PySceneDetect 封装，确定性、可复现）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--video` |  | 必填 |
| `--start` |  |  |
| `--end` |  | 默认: `1000000000.0` |
| `--threshold` |  | 默认: `27.0` |
| `--min-len` |  | 默认: `0.4` |
| `--json` |  |  |
| `--frames` |  |  |

## `validate_45s.py`

validate_45s.py — 三轮校验（人物 / 音频 / 叙事）。任一项不过 → 退出码 1，禁止输出成片。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--video` |  | 必填 |
| `--voice` |  | 必填 |
| `--bgm` |  | 必填 |
| `--timeline` |  | 必填 |
| `--report` |  | 必填 |

## `validate_narrative.py`

validate_narrative.py — 叙事连贯性 / J-cut 分级校验（block / warn）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--timeline` |  | 必填 |
| `--shots` |  |  |
| `--forbidden` |  |  |
| `--emotion-script` |  |  |
| `--allow-jcut` |  | 开关 |
| `--no-allow-jcut` |  |  |
| `--out` |  | 默认: `validate_narrative_report.json` |
| `--md` |  |  |

## `verify_asset.py`

verify_asset.py — 素材下载、验证与清单登记（Phase 2.1）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--url` |  | 必填 |
| `--project-dir` |  | 必填 |
| `--title` |  | 默认: `untitled` |
| `--source-name` |  | 默认: `manual-url` |
| `--manifest-name` |  | 默认: `assets_manifest.json` |

## `video_qc.py`

video_qc.py — 成片质检（Phase 2.4，v2 增加时长守卫/冻结/静音检测）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--video` |  | 必填 |
| `--out` |  | 必填 |
| `--plan-json` | montage_edit.py 报告 JSON（含 planned_duration），用于时长守卫 |  |
| `--plan-duration` | 直接给定计划时长（秒）；与 --plan-json 二选一 |  |
| `--tolerance` | 时长守卫容差（秒），默认取内置 1.0 |  |
| `--max-freeze` | 画面冻结累计上限（秒），默认取内置 3.0；固定机位空镜多文艺片项目可显式放宽（冻结事实仍完整记录） |  |

## `win_asr.py`

win_asr.py — 对指定时间窗做本地转写（faster-whisper，CPU，无需联网付费）。

| 参数 | 说明 | 备注 |
|---|---|---|
| `--video` |  | 必填 |
| `--start` |  | 必填 |
| `--end` |  | 必填 |
| `--model` |  | 默认: `small` |
| `--json` |  |  |
