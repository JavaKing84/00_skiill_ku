#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_skill_demo.py — 模块4 最小单元测试（只打印 filter 字符串 + 输出诊断 json，禁止生成视频）。

验证：
  1) 四个函数都能产出可用的 filter 字符串
  2) 淡入淡出时间轴计算正确（45s 片、2.8s 淡出 → 起点 42.20s）
  3) 对真实音轨做诊断：短片64（含"世界是一片荒原"台词）+ 志铭.m4a（BGM）
输出：demo_out/audio_diagnose.json、audio_skill_demo.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"D:\00_skiill_ku\03_video")
SCRIPTS = ROOT / "scripts"
OUT = ROOT / "demo_out"
RAW = ROOT / "assets" / "elephant" / "raw"
BGM = ROOT / "assets" / "elephant" / "bgm" / "志铭.m4a"

sys.path.insert(0, str(SCRIPTS))
from audio_skill import (audio_diagnose, audio_ducking, audio_fade_in_out,  # noqa: E402
                         audio_segment_normalize, report_md)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    duck = audio_ducking("0:a", "1:a", threshold=0.028, ratio=9, attack=6, release=380,
                         bgm_gain_db=-19)
    dyn = audio_segment_normalize("dynaudnorm", frame_ms=500, gauss=11, peak=0.9)
    loud = audio_segment_normalize("loudnorm", target_i=-16, tp=-1.5, lra=11)
    fade = audio_fade_in_out(2.5, 2.8, 45.0, "tri")

    checks = {
        "ducking_has_sidechain": "sidechaincompress" in duck and "ratio=9" in duck,
        "dynaudnorm_ok": dyn.startswith("dynaudnorm=f=500:g=11:p=0.9"),
        "loudnorm_ok": loud.startswith("loudnorm=I=-16:TP=-1.5:LRA=11"),
        "fade_ok": "st=42.20" in fade and "d=2.5" in fade and "d=2.8" in fade,
    }

    # 台词窗口为已核验的"世界是一片荒原"（短片64 22.55-24.35）
    rep = audio_diagnose(RAW / "短片64.mp4", BGM if BGM.exists() else None,
                         speech_windows=[[22.55, 24.35]])
    (OUT / "audio_diagnose.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    md = ["# 模块4 音频封装 Demo 报告", "",
          "## 生成的 filter 字符串（未渲染）", "",
          "```text", "[ducking] " + duck, "[dynaudnorm] " + dyn,
          "[loudnorm] " + loud, "[fade] " + fade, "```", "",
          "| 检查 | 结果 |", "|---|---|"]
    md += [f"| {k} | {'PASS' if v else 'FAIL'} |" for k, v in checks.items()]
    md += ["", report_md(rep)]
    (OUT / "audio_skill_demo.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("[ducking]", duck)
    print("[dynaudnorm]", dyn)
    print("[loudnorm]", loud)
    print("[fade]", fade)
    print("diagnose:", json.dumps({k: rep[k] for k in
                                   ("bgm_entry_sec", "voice_db", "voice_bgm_diff",
                                    "ducking_db", "flags") if k in rep}, ensure_ascii=False))
    ok = all(checks.values()) and rep.get("voice_db") is not None
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
