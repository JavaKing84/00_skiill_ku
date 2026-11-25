"""shot_detector.py — 用 ffmpeg 原生 scene 滤镜替代 PySceneDetect 的 Python 逐帧循环。

原理：ffmpeg -vf "select='gt(scene,0.3)',showinfo" 直接在 C 层做帧差镜头检测，
比 OpenCV/Python 逐帧快数倍；长视频（43 分钟）从 ~15 分钟降到 ~1-2 分钟。

兼容旧接口：detect(video, start, end, threshold, min_len) -> [{"start":..,"end":..}, ...]
可直接被 scripts/shot_analyze.py 导入替换 from shot_detect import detect。

CLI:
  python adapters/shot_detector.py --video a.mp4 [--start 0 --end 60 --threshold 0.3 --min-len 0.4 --out shots.json]
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from .ffmpeg_utils import run_ffmpeg, probe_duration

_SHOWINFO_RE = re.compile(r"pts_time:([0-9.]+)")


def detect(video: str | Path, start: float = 0.0, end: float | None = None,
           threshold: float = 0.3, min_len: float = 0.4) -> list[dict]:
    """返回镜头边界列表，每项 {"start": float, "end": float}（秒，相对视频起点）。"""
    video = str(video)
    if end is None:
        end = probe_duration(video)
    # ffmpeg scene 滤镜输出 showinfo 到 stderr，解析 pts_time 即为切点
    cmd = ["-hide_banner", "-v", "info", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
           "-i", video, "-vf", f"select='gt(scene,{threshold})',showinfo",
           "-an", "-f", "null", "-"]
    cp = run_ffmpeg(cmd)
    cuts = [0.0]
    for line in cp.stderr.splitlines():
        m = _SHOWINFO_RE.search(line)
        if m:
            cuts.append(start + float(m.group(1)))
    cuts.append(end)
    # 去重 + 过滤过短镜头
    merged: list[dict] = []
    for i in range(len(cuts) - 1):
        s, e = cuts[i], cuts[i + 1]
        if e - s < min_len and merged:
            merged[-1]["end"] = e  # 合并到上一镜
        else:
            merged.append({"start": round(s, 3), "end": round(e, 3)})
    return merged


def main() -> int:
    ap = argparse.ArgumentParser(description="ffmpeg scene 滤镜镜头边界检测（CPU 加速）")
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--threshold", type=float, default=0.3, help="scene 阈值 0~1，越小切点越多")
    ap.add_argument("--min-len", type=float, default=0.4)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    t0 = time.time()
    shots = detect(a.video, a.start, a.end, a.threshold, a.min_len)
    dt = time.time() - t0
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"shots={len(shots)}  elapsed={dt:.2f}s  -> {a.out or '(stdout)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
