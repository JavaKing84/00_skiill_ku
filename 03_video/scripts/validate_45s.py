#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_45s.py — 三轮校验（人物 / 音频 / 叙事）。任一项不过 → 退出码 1，禁止输出成片。

音频校验用分离测量：voice 轨（base45，纯原声）与 bgm 轨（按同样 ducking 链单独渲染），
避免把原片环境声/配乐误当成 BGM。

用法：
  python validate_45s.py --video final.mp4 --voice base45.mp4 --bgm 志铭.m4a \
      --timeline timeline_45s.json --report validate_report.md
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

SR = 16000
WHITELIST_RANGES = [
    ("导剪001.mp4", 524.0, 531.0), ("导剪001.mp4", 527.0, 535.5),
    ("导剪001.mp4", 1042.0, 1057.5), ("导剪001.mp4", 465.0, 491.0),
    ("导剪002.mp4", 1632.0, 1649.5), ("短片64.mp4", 22.4, 24.4),
]
FORBIDDEN_RANGES = [("导剪001.mp4", 1008.0, 1032.0), ("导剪001.mp4", 1408.0, 1432.0)]


def decode(path: str) -> np.ndarray:
    tmp = Path(tempfile.mkdtemp(prefix="val_")) / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path, "-vn", "-ac", "1",
                    "-ar", str(SR), str(tmp)], check=True)
    with wave.open(str(tmp), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def render_bgm_only(base: str, bgm: str, dur: float) -> np.ndarray:
    """按成片同样的 BGM 增益与 ducking 单独渲染 BGM 轨，用于独立性测量。"""
    tmp = Path(tempfile.mkdtemp(prefix="bgm_")) / "b.wav"
    fc = (f"[0:a]atrim=0:{dur},asetpts=PTS-STARTPTS,volume=-16dB,afade=t=in:st=0:d=2.5[b];"
          f"[1:a]asplit=1[sc];[b][sc]sidechaincompress=threshold=0.08:ratio=3:attack=10:release=500[d];"
          f"[d]afade=t=out:st=42.2:d=2.8[a]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", bgm, "-i", base, "-filter_complex", fc,
                    "-map", "[a]", "-ac", "1", "-ar", str(SR), str(tmp)], check=True)
    with wave.open(str(tmp), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def band_rms(x: np.ndarray, t0: float, t1: float, lo=300, hi=4000) -> float:
    a, b = int(t0 * SR), int(t1 * SR)
    seg = x[max(0, a):max(1, b)]
    if seg.size < 512:
        return -120.0
    X = np.fft.rfft(seg)
    fr = np.fft.rfftfreq(seg.size, 1 / SR)
    X[(fr < lo) | (fr > hi)] = 0
    y = np.fft.irfft(X, n=seg.size)
    return 20 * np.log10(max(float(np.sqrt(np.mean(y ** 2))), 1e-9))


def check_people(tl: dict) -> list[str]:
    errs = []
    for s in tl["sections"]:
        for v in (s.get("video_sequence") or [s.get("video", {})]):
            src, tin = v.get("src"), v.get("in")
            if src is None or tin is None:
                continue
            a, b = tin, tin + v.get("dur", 0)
            if not any(src == ws and a >= x - 0.01 and b <= y + 0.01 for ws, x, y in WHITELIST_RANGES):
                errs.append(f"[人物] {s['id']} {src} {a:.2f}-{b:.2f} 不在人物白名单区间")
            if any(src == fs and not (b <= x or a >= y) for fs, x, y in FORBIDDEN_RANGES):
                errs.append(f"[人物] {s['id']} 命中被剔除支线 {src} {a:.1f}-{b:.1f}")
    return errs


def check_audio(final: np.ndarray, voice: np.ndarray, bgm: np.ndarray) -> tuple[list[str], dict]:
    errs, st = [], {}
    speech = [(0.05, 1.85),
              (3.70, 6.73),
              (11.19, 17.86),
              (18.00, 20.94),
              (22.42, 33.38),
              (33.38, 42.74)]
    gaps = [(2.30, 2.90), (9.20, 9.85), (42.90, 44.20)]

    v_gap = [band_rms(voice, a, b) for a, b in gaps]
    b_gap = [band_rms(bgm, a, b) for a, b in gaps]
    st["voice_gap_db"] = [round(v, 1) for v in v_gap]
    st["bgm_gap_db"] = [round(v, 1) for v in b_gap]

    for i, (a, b) in enumerate(speech, 1):
        v = band_rms(voice, a, b)
        g = band_rms(bgm, a, b)
        st[f"line{i}"] = {"voice": round(v, 1), "bgm": round(g, 1), "margin": round(v - g, 1)}
        if v < -32:
            errs.append(f"[音频] 第{i}句原声仅 {v:.1f}dB（低于-32dB，疑似丢失）")
        if v - g < 8:
            errs.append(f"[音频] 第{i}句人声仅高出BGM {v-g:.1f}dB（要求≥8dB，会被盖）")

    # 压侧：说话时 BGM 整体应低于空档（用中位数，避免单点误差）
    duck = sorted(band_rms(bgm, a, b) - max(b_gap) for a, b in speech)
    med = (duck[2] + duck[3]) / 2
    st["duck_db"] = [round(d, 1) for d in duck]
    st["duck_median_db"] = round(med, 1)
    if med > -2:
        errs.append(f"[音频] BGM 压侧中位数 {med:.1f}dB 不足（ducking 未生效）")

    if min(b_gap) < -52:
        errs.append(f"[音频] 空档BGM最低 {min(b_gap):.1f}dB，开篇/全程铺垫不足")
    tail = band_rms(final, 44.4, 45.0)
    st["tail_db"] = round(tail, 1)
    if tail > max(band_rms(final, 40.0, 41.8), -80) - 6:
        errs.append(f"[音频] 结尾 {tail:.1f}dB 未衰减，收尾突兀")
    return errs, st


def check_narrative(tl: dict) -> list[str]:
    errs = []
    if [s["id"] for s in tl["sections"]] != ["S1", "S2", "S3", "S4", "S5"]:
        errs.append("[叙事] 段落顺序错误")
    total = sum(s["dur"] for s in tl["sections"])
    if not 44.5 <= total <= 45.5:
        errs.append(f"[叙事] 总时长 {total:.2f}s 不在 45±0.5")
    if tl["sections"][3]["dur"] < 20:
        errs.append("[叙事] 独白锚点过短")
    roles = {s.get("role") for s in tl["sections"]}
    if not roles <= set(tl["characters_whitelist"]) | {"三人交叉"}:
        errs.append(f"[叙事] 白名单外主角: {roles}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--voice", required=True)
    ap.add_argument("--bgm", required=True)
    ap.add_argument("--timeline", required=True)
    ap.add_argument("--report", required=True)
    a = ap.parse_args()

    tl = json.loads(Path(a.timeline).read_text(encoding="utf-8"))
    final = decode(a.video)
    voice = decode(a.voice)
    bgm = render_bgm_only(a.voice, a.bgm, len(final) / SR)

    e1 = check_people(tl)
    e2, st = check_audio(final, voice, bgm)
    e3 = check_narrative(tl)
    allerr = e1 + e2 + e3

    lines = ["# 三轮校验报告", "", f"- 成片: `{a.video}`", f"- 时长: {len(final)/SR:.2f}s", ""]
    for name, errs in (("① 人物校验", e1), ("② 音频校验", e2), ("③ 叙事校验", e3)):
        lines.append(f"## {name}: {'PASS' if not errs else 'FAIL'}")
        lines += [f"- {e}" for e in errs] or ["- 通过"]
        lines.append("")
    lines += ["## 音频分离测量", "```", json.dumps(st, ensure_ascii=False, indent=1), "```"]
    Path(a.report).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print("\nVERDICT:", "PASS" if not allerr else "FAIL")
    return 0 if not allerr else 1


if __name__ == "__main__":
    raise SystemExit(main())
