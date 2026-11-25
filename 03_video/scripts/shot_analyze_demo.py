#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot_analyze_demo.py — 模块2 最小单元测试（仅输出分析数据，不渲染视频）。

用《大象席地而坐》短片64（64s，切点密集）做验证：
  - PySceneDetect 切出镜头数应 >= 3
  - 景别至少出现 2 种
  - motion_score 应有高低差异（静态/运动镜头都存在）
输出：demo_out/shot_analyze_result.json、shot_analyze_demo.md
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r"D:\00_skiill_ku\03_video")
SCRIPTS = ROOT / "scripts"
OUT = ROOT / "demo_out"
RAW = ROOT / "assets" / "elephant" / "raw"

sys.path.insert(0, str(SCRIPTS))
from shot_analyze import analyze  # noqa: E402


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    video = RAW / "短片64.mp4"
    shots = analyze(video, 0.0, 64.0)
    out_json = OUT / "shot_analyze_result.json"
    out_json.write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")

    scales = Counter(s["shot_scale"] for s in shots)
    motions = [s["motion_score"] for s in shots]
    long_n = sum(s["is_long_shot"] for s in shots)
    ok = len(shots) >= 3 and len(scales) >= 2 and (max(motions) - min(motions)) > 0.15 if motions else False

    md = ["# 模块2 镜头语义解析 Demo 报告", "",
          f"- 素材：`{video.name}` 0-64s",
          f"- 镜头数：{len(shots)}；景别分布：{dict(scales)}；长镜头：{long_n}",
          f"- motion_score：min {min(motions):.2f} / max {max(motions):.2f}" if motions else "",
          f"- 自检：{'PASS' if ok else 'FAIL'}", "",
          "| shot_id | start | end | 时长 | 景别 | 人脸占比 | motion | 长镜头 |",
          "|---|---|---|---|---|---|---|---|"]
    for s in shots:
        md.append(f"| {s['shot_id']} | {s['start_time']} | {s['end_time']} | {s['duration']} | "
                  f"{s['shot_scale']} | {s['face_area_ratio']} | {s['motion_score']} | "
                  f"{int(s['is_long_shot'])} |")
    md += ["", "## 阈值（本片标定，换片需校准）",
           "- 特写 face_area_ratio ≥ 0.22；近景 0.12–0.22；中景 0.05–0.12；远景 < 0.05",
           "- motion_score > 0.25 视为明显运动/手持；< 0.05 视为静态",
           "- 时长 ≥ 6s 记为长镜头", "",
           "> 局限：完全背身、全黑画面、纯空镜无法判景别（记为远景且 face_area_ratio=0）；快速摇镜会让 motion_score 虚高。"]
    (OUT / "shot_analyze_demo.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"shots={len(shots)} scales={dict(scales)} long={long_n} "
          f"motion={min(motions):.2f}-{max(motions):.2f} -> {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
