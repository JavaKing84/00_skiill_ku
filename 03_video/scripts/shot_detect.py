#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot_detect.py — 镜头边界检测（PySceneDetect 封装，确定性、可复现）。

解决的核心问题：凭感觉设切点会把剪辑切在半句话/半个动作上，成片显得"很 AI"。
本脚本给出源素材真实镜头切点，让 EDL 的 start/dur 对齐镜头边界。

用法：
  python shot_detect.py --video a.mp4 --start 428 --end 620 [--threshold 27] [--json out.json]
  python shot_detect.py --video a.mp4 --start 428 --end 620 --frames outdir   # 每个镜头首帧落盘
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from scenedetect import ContentDetector, SceneManager, open_video


def detect(video: str, start: float, end: float, threshold: float = 27.0,
           min_len: float = 0.4) -> list[dict]:
    # 先用 ffmpeg 精确切出窗口（-c copy 无法精确，故重编码到临时文件），
    # 再整段做检测，最后把时间戳偏移回源时间轴。避免依赖不同版本 SceneManager 的区间参数。
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="shot_")) / "win.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                    "-i", video, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                    "-an", str(tmp)], check=True)
    vs = open_video(str(tmp))
    fps = vs.frame_rate
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold,
                                    min_scene_len=max(1, int(min_len * fps))))
    sm.detect_scenes(video=vs, show_progress=False)
    shots = []
    for sc in sm.get_scene_list(start_in_scene=True):
        a, b = start + sc[0].get_seconds(), start + sc[1].get_seconds()
        a, b = max(a, start), min(b, end)
        if b - a >= min_len:
            shots.append({"start": round(a, 2), "end": round(b, 2), "dur": round(b - a, 2)})
    return shots


def dump_frames(video: str, shots: list[dict], outdir: Path, width: int = 320) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for i, s in enumerate(shots, 1):
        p = outdir / f"shot_{i:02d}_{s['start']:.1f}.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s['start'] + 0.05:.2f}",
                        "-i", video, "-frames:v", "1",
                        "-vf", f"scale={width}:-2", str(p)], check=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=1e9)
    ap.add_argument("--threshold", type=float, default=27.0)
    ap.add_argument("--min-len", type=float, default=0.4)
    ap.add_argument("--json", default="")
    ap.add_argument("--frames", default="")
    a = ap.parse_args()

    shots = detect(a.video, a.start, a.end, a.threshold, a.min_len)
    print(f"shots={len(shots)}  range={a.start}-{a.end}  video={Path(a.video).name}")
    for i, s in enumerate(shots, 1):
        print(f"  {i:02d}  {s['start']:8.2f} -> {s['end']:8.2f}  ({s['dur']:5.2f}s)")
    if a.json:
        Path(a.json).write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.frames:
        dump_frames(a.video, shots, Path(a.frames))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
