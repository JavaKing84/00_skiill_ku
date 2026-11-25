#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reference_analyze.py — 参考视频逆向分析（Phase 2.2）。

输出：
  <out>/reference_timeline.csv   start,end,visual,shot_motion,confidence
  <out>/reference_style.json     可机读风格配置；推断项标 "inferred": true
  <out>/frames/                  切换点与首中尾抽帧

只分析用户有权处理的本地文件，不上传任何外部服务。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
from skillkit.media import ffprobe, summarize, scene_cuts, extract_frames  # noqa: E402


def build_timeline(duration: float, cuts: list[float]) -> list[dict]:
    """把切换点转成镜头区间；画面描述留空待模型/人工填，置信度给机器值。"""
    bounds = [0.0] + cuts + [duration]
    rows = []
    for i in range(len(bounds) - 1):
        start, end = round(bounds[i], 3), round(bounds[i + 1], 3)
        rows.append({
            "start": start,
            "end": end,
            "visual": "",          # 由模型看帧后填写，禁止脚本编造画面内容
            "shot_motion": "",
            "subtitle": "",
            "audio": "",
            "transition": "cut" if i > 0 else "start",
            "confidence": 0.6,     # 机器仅对边界有把握；内容置信度待人工/视觉模型补
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scene-threshold", type=float, default=0.35)
    args = ap.parse_args()

    video = Path(args.video)
    if not video.exists():
        print(f"FAIL: video not found: {video}", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    probe = ffprobe(video)
    meta = summarize(probe)
    duration = meta["duration_seconds"] or 0.0
    cuts = scene_cuts(video, threshold=args.scene_threshold)

    # 抽帧：首、中、尾 + 最多前 6 个切换点
    stamps = sorted({0.0, round(duration / 2, 3), max(0.0, duration - 0.1)} | set(cuts[:6]))
    frames = extract_frames(video, stamps, out / "frames")

    timeline = build_timeline(duration, cuts)
    with open(out / "reference_timeline.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(timeline[0].keys()))
        writer.writeheader()
        writer.writerows(timeline)

    v = meta["video"] or {}
    style = {
        "schema": "reference-style-v1",
        "source_file": str(video),
        "probe": meta,
        "shot_count": len(timeline),
        "avg_shot_seconds": round(duration / len(timeline), 3) if timeline else None,
        "scene_cuts": cuts,
        "frames_extracted": [str(p) for p in frames],
        "visual_style": {
            "aspect_ratio": f"{v.get('width')}:{v.get('height')}" if v else None,
            "color_grade": None,           # 需视觉分析，标记未取得
            "subtitle_rule": None,
            "transition_rule": "cut-only-detected",
        },
        "inferred_fields": ["avg_shot_seconds", "transition_rule"],
        "note": "None 字段为未取得而非默认值；visual/shot_motion 需模型看 frames/ 后补全，禁止凭空填写。",
    }
    (out / "reference_style.json").write_text(json.dumps(style, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK shots={len(timeline)} cuts={len(cuts)} frames={len(frames)} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
