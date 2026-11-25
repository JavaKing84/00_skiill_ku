---
name: 03-video-pipeline
description: 视频剪辑与成片生产标准流水线（素材验证 → 参考分析 → 渲染 → QC → 发布 dry-run）。当用户要求剪辑视频、把素材做成成片、合并多段视频、复刻参考视频节奏、添加字幕/花字/配音/BGM/转场、输出 9:16 16:9 1:1 画幅、批量剪辑、压缩导出、检查黑屏无声损坏、生成发布预览时触发。
version: 1.0.0
triggers: [剪辑, 成片, 合并视频, 参考视频, 字幕, 花字, 配音, BGM, 转场, 画幅, 竖屏, 批量剪辑, 压缩导出, 成片质检, 黑屏, 无声, 发布预览]
not_triggers: [只分析视频内容, 只下载视频, 视频生成技术研究, 纯图片修图, 只讨论剪辑理论, 普通问答]
entry: ../../../03_video/SKILL.md
scripts_dir: ../../../03_video/scripts
executor: ../../../03_video/aitoearn（真实剪辑执行）
---

# 03-video-pipeline

跨客户端标准入口。业务规则以 [`03_video/SKILL.md`](../../../03_video/SKILL.md) 为唯一来源，
本文件只声明触发边界与调用路径，避免复制规则产生分歧。

## 路径映射

| 能力 | 实际路径 |
|---|---|
| 业务规则（canonical） | `../../../03_video/SKILL.md` |
| 剪辑执行器 | `../../../03_video/aitoearn/` |
| 渲染 / 质检脚本 | `../../../03_video/scripts/` |
| 素材与 BGM 许可台账 | `../../../03_video/assets/BGM_LICENSES.json` |

## 常用命令（在库根目录 `D:\00_skiill_ku` 下执行）

```bash
# 成片质检（必须对真实导出文件执行）
python 03_video/scripts/video_qc.py --video <成片.mp4> --out <QC目录>

# 素材校验
python 03_video/scripts/verify_asset.py --path <素材路径>

# 发布预览（默认 dry-run，不真实发布）
python 03_video/scripts/publish_preview.py --video <成片.mp4>
```

## 硬约束

- 必须实际调用执行器/脚本，禁止只给方案。
- 成片必须用 ffprobe 校验（时长、分辨率、帧率、音视频流），不能只看返回码。
- 真实公开发布须逐次人工批准；默认 dry-run。
- BGM 必须登记在 `BGM_LICENSES.json`，版权不明不得使用。
