#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot_analyze.py — 镜头语义解析（景别 / 运动量 / 长短镜头），纯 CPU。

复用 PySceneDetect 做镜头边界（与 shot_detect.py 同一套算法），再逐镜抽帧：
  - 人脸占比 → 景别：特写 / 近景 / 中景 / 远景
  - 相邻帧灰度差 → motion_score（0=静止，1=剧烈运动/抖动）
  - 时长阈值 → is_long_shot
不调用任何视觉大模型，1080p 素材每秒可处理数十帧。

输出 JSON 字段（严格）：
  shot_id,start_time,end_time,shot_scale,face_area_ratio,motion_score,is_long_shot
另附只读辅助字段：source,duration,frames_sampled,no_face

用法：
  python shot_analyze.py --video a.mp4 --start 1600 --end 1720 --out shot_analyze_result.json
  python shot_analyze.py --video a.mp4 --start 1600 --end 1720 --frames outdir   # 逐镜首帧（可选）
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shot_detect import detect as detect_shots  # noqa: E402  复用已验证的切点检测
from person_scan import FaceEngine  # noqa: E402  复用 YuNet+SFace 引擎（避免重复实现）

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
DET_MODEL = MODEL_DIR / "face_detection_yunet_2023mar.onnx"

# 景别人脸占比阈值（本片标定，换片需重新校准）
SCALE_THRESHOLDS = [(0.22, "特写"), (0.12, "近景"), (0.05, "中景"), (0.0, "远景")]
LONG_SHOT_SEC = 6.0
MOTION_STRONG = 0.25


def classify_scale(ratio: float) -> str:
    for thr, name in SCALE_THRESHOLDS:
        if ratio >= thr:
            return name
    return "远景"


def sample_frames(video: Path, start: float, end: float, fps: float, outdir: Path,
                  width: int = 960) -> list[tuple[float, Path]]:
    outdir.mkdir(parents=True, exist_ok=True)
    pattern = outdir / "s_%06d.jpg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                    "-i", str(video), "-vf", f"fps={fps},scale={width}:-2", "-q:v", "3",
                    str(pattern)], check=True)
    files = sorted(outdir.glob("s_*.jpg"))
    return [(start + i / fps, p) for i, p in enumerate(files)]


def analyze(video: Path, start: float, end: float, threshold: float = 27.0,
            min_len: float = 0.4, sample_fps: float = 2.0,
            long_shot_sec: float = LONG_SHOT_SEC, min_face_px: int = 40) -> list[dict]:
    shots = detect_shots(str(video), start, end, threshold, min_len)
    if not shots:
        return []
    if not DET_MODEL.exists() or DET_MODEL.stat().st_size < 1024:
        raise FileNotFoundError(f"缺少人脸检测模型：{DET_MODEL}（下载地址见 SKILL.md）")

    tmp = Path(tempfile.mkdtemp(prefix="shotan_"))
    frames = sample_frames(video, start, end, sample_fps, tmp)
    engine = FaceEngine(0.65, 0.3)

    out = []
    for i, s in enumerate(shots, 1):
        inside = [(t, p) for t, p in frames if s["start"] - 0.05 <= t < s["end"] - 0.01]
        max_ratio, prev_gray, diffs = 0.0, None, []
        for t, p in inside:
            img = cv2.imread(str(p))
            if img is None:
                continue
            h, w = img.shape[:2]
            for f in engine.detect(img, min_face_px):
                max_ratio = max(max_ratio, float(f[2] * f[3]) / float(w * h))
            gray = cv2.cvtColor(cv2.resize(img, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.float32)
            if prev_gray is not None:
                diffs.append(float(np.mean(np.abs(gray - prev_gray))))
            prev_gray = gray
        motion = 0.0 if not diffs else min(1.0, (sum(diffs) / len(diffs)) / 30.0)
        dur = round(s["end"] - s["start"], 2)
        out.append({
            "shot_id": f"S{i:03d}",
            "start_time": round(s["start"], 2),
            "end_time": round(s["end"], 2),
            "shot_scale": classify_scale(max_ratio),
            "face_area_ratio": round(max_ratio, 4),
            "motion_score": round(motion, 3),
            "is_long_shot": bool(dur >= long_shot_sec),
            # 以下为辅助字段
            "source": str(video),
            "duration": dur,
            "frames_sampled": len(inside),
            "no_face": max_ratio <= 0.0,
        })
    return out


def dump_first_frames(video: Path, shots: list[dict], outdir: Path, width: int = 320) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for s in shots:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s['start_time'] + 0.05:.2f}",
                        "-i", str(video), "-frames:v", "1", "-vf", f"scale={width}:-2",
                        str(outdir / f"{s['shot_id']}_{s['start_time']:.1f}.jpg")], check=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="镜头语义解析（景别/运动/长短镜头）")
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=60.0)
    ap.add_argument("--threshold", type=float, default=27.0)
    ap.add_argument("--min-len", type=float, default=0.4)
    ap.add_argument("--sample-fps", type=float, default=2.0)
    ap.add_argument("--long-shot-sec", type=float, default=LONG_SHOT_SEC)
    ap.add_argument("--out", default="shot_analyze_result.json")
    ap.add_argument("--frames", default="")
    a = ap.parse_args()

    shots = analyze(Path(a.video), a.start, a.end, a.threshold, a.min_len,
                    a.sample_fps, a.long_shot_sec)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.frames:
        dump_first_frames(Path(a.video), shots, Path(a.frames))
    print(f"shots={len(shots)} -> {a.out}")
    for s in shots:
        print(f"  {s['shot_id']} {s['start_time']:8.2f}-{s['end_time']:8.2f} "
              f"{s['shot_scale']:<2} face={s['face_area_ratio']:.3f} "
              f"motion={s['motion_score']:.2f} long={int(s['is_long_shot'])}")
    return 0 if shots else 2


if __name__ == "__main__":
    raise SystemExit(main())
