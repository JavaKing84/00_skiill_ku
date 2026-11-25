#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""win_asr.py — 对指定时间窗做本地转写（faster-whisper，CPU，无需联网付费）。

用途：在已确认的电影段落里补出角色台词与词级时间戳，避免"凭记忆猜台词"。
用法：
  python win_asr.py --video a.mp4 --start 468 --end 505 --model small --json out.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--model", default="small")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="asr_")) / "w.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(a.start), "-to", str(a.end),
                    "-i", a.video, "-vn", "-ac", "1", "-ar", "16000", str(tmp)], check=True)

    from faster_whisper import WhisperModel
    m = WhisperModel(a.model, device="cpu", compute_type="int8")
    segs, _ = m.transcribe(str(tmp), language="zh", vad_filter=True,
                           vad_parameters={"min_silence_duration_ms": 300},
                           beam_size=5, condition_on_previous_text=False)
    out = [{"start": round(a.start + s.start, 2), "end": round(a.start + s.end, 2),
            "text": s.text.strip()} for s in segs]
    for s in out:
        print(f"  {s['start']:8.2f} -> {s['end']:8.2f}  {s['text']}")
    print(f"segments={len(out)}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
