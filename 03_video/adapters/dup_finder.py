"""dup_finder.py — 视频去重，抛弃逐帧全量哈希。

两级策略：
  1) 片内去重（同一条素材内部相邻重复帧）：ffmpeg mpdecimate 滤镜，C 层极快。
  2) 跨素材近重复检测：videohash（感知哈希，基于 ffmpeg 抽帧），比较两条视频是否近重复。

若未安装 videohash，跨素材检测会给出明确 BLOCKED 提示并降级为"仅片内去重"，
不伪造相似度数值。

CLI:
  python adapters/dup_finder.py --video a.mp4 --mode internal        # 片内
  python adapters/dup_finder.py --video a.mp4 --video2 b.mp4 --mode cross  # 跨素材
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .ffmpeg_utils import run_ffmpeg, probe_duration


def dedup_internal(video: str | Path, out: str | Path | None = None) -> dict:
    """片内去重：mpdecimate 丢弃与前一帧相同的帧，输出去重后视频 + 统计。"""
    video = str(video)
    dur = probe_duration(video)
    out = out or str(Path(video).with_suffix(".dedup.mp4"))
    cmd = ["-y", "-hide_banner", "-i", video,
           "-vf", "mpdecimate=hi=64*12:lo=64*5:frac=0.33,setpts=N/FRAME_RATE/TB",
           "-an", str(out)]
    t0 = time.time()
    cp = run_ffmpeg(cmd)
    dt = time.time() - t0
    dropped = 0
    for line in cp.stderr.splitlines():
        if "drop_count" in line or "mpdecimate" in line.lower():
            pass  # 新版 ffmpeg 不直接打印 drop 数，用时长差估算
    try:
        from .ffmpeg_utils import probe_duration as pd
        out_dur = pd(out)
    except Exception:
        out_dur = dur
    return {
        "mode": "internal",
        "source": video,
        "output": out,
        "input_duration": round(dur, 2),
        "output_duration": round(out_dur, 2),
        "estimated_removed_ratio": round(1 - out_dur / dur, 3) if dur else 0.0,
        "elapsed_sec": round(dt, 2),
    }


def dedup_cross(video_a: str | Path, video_b: str | Path) -> dict:
    """跨素材近重复：videohash 汉明距离；距离越小越相似（<10 通常近重复）。"""
    try:
        from videohash import VideoHash  # type: ignore
    except ImportError:
        return {"mode": "cross", "blocked": True,
                "reason": "未安装 videohash：pip install videohash（依赖 ffmpeg/ImageMagick）。"
                          "已降级为仅片内去重，不伪造相似度。"}
    t0 = time.time()
    ha = VideoHash(path=str(video_a))
    hb = VideoHash(path=str(video_b))
    dist = ha - hb
    return {
        "mode": "cross",
        "video_a": str(video_a), "video_b": str(video_b),
        "hamming_distance": int(dist),
        "near_duplicate": bool(dist < 10),
        "elapsed_sec": round(time.time() - t0, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="视频去重（片内 mpdecimate / 跨素材 videohash）")
    ap.add_argument("--video", required=True)
    ap.add_argument("--video2", default="")
    ap.add_argument("--mode", choices=["internal", "cross"], default="internal")
    ap.add_argument("--out", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    if a.mode == "internal":
        res = dedup_internal(a.video, a.out or None)
    else:
        if not a.video2:
            print("cross 模式需要 --video2"); return 2
        res = dedup_cross(a.video, a.video2)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
