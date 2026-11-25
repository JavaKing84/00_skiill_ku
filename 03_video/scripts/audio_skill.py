#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_skill.py — 把混音逻辑封装成可调用函数，避免每次手写超长 filter_complex。

只做两件事：生成 **ffmpeg filter 字符串** + 对音轨做 **数值诊断**；不渲染、不落视频。

四个函数：
  audio_ducking()            人声触发 BGM 侧链压缩（sidechaincompress）
  audio_segment_normalize()  分段/整轨响度归一（dynaudnorm | loudnorm）
  audio_fade_in_out()        淡入淡出
  audio_diagnose()           BGM 入场时间 / 台词能量丢失 / 人声-BGM 响度差 / 压侧量

约定：label 用 ffmpeg filter_complex 的输入标签，例如人声是第 0 路音频传 "0:a"，
BGM 是第 1 路传 "1:a"。

用法：
  from audio_skill import audio_ducking, audio_segment_normalize, audio_fade_in_out
  fc = (f"[1:a]{audio_segment_normalize('dynaudnorm')}[bgm];"
        f"{audio_ducking('0:a', 'bgm')};"          # 输出 [bgmduck]
        f"[0:a][bgmduck]amix=inputs=2:duration=first:dropout_transition=0[aout]")
  # 再把 fc 交给 ffmpeg -filter_complex
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

SR = 16000
FRAME_MS = 50


# ---------------------------------------------------------------- filter 生成
def audio_ducking(voice_label: str = "0:a", bgm_label: str = "1:a",
                  threshold: float = 0.05, ratio: float = 6.0,
                  attack: float = 8.0, release: float = 420.0,
                  makeup: float = 1.0, sc_level: float = 1.0,
                  bgm_gain_db: float = -3.0, out_label: str = "bgmduck") -> str:
    """人声优先：人声出现时把 BGM 压下去，人声结束后自动回升。

    threshold: 侧链触发阈值（线性 0-1，0.03-0.08 通常合适）
    ratio:     压缩比（3-9；越大压得越狠）
    attack/release: 毫秒（attack 6-10，release 380-500，避免"呼吸感"）
    makeup:    压缩后补偿增益（线性）
    """
    pre = f"[{bgm_label}]volume={bgm_gain_db}dB[bgm_pre];" if bgm_gain_db else ""
    src = "[bgm_pre]" if bgm_gain_db else f"[{bgm_label}]"
    return (f"{pre}{src}[{voice_label}]sidechaincompress="
            f"threshold={threshold}:ratio={ratio}:attack={attack}:release={release}"
            f":makeup={makeup}:level_sc={sc_level}[{out_label}]")


def audio_segment_normalize(mode: str = "dynaudnorm", *, target_i: float = -16.0,
                            tp: float = -1.5, lra: float = 11.0,
                            frame_ms: int = 500, gauss: int = 11, peak: float = 0.9,
                            max_gain: float = 10.0) -> str:
    """响度归一。dynaudnorm 适合"同一段里忽大忽小"；loudnorm 适合整轨对齐平台标准。

    注意：loudnorm 单遍模式是动态的，要精确达标应做两遍（先测后校），本函数只给单遍链。
    """
    if mode == "dynaudnorm":
        return (f"dynaudnorm=f={frame_ms}:g={gauss}:p={peak}:m={max_gain}:s=0")
    if mode == "loudnorm":
        return f"loudnorm=I={target_i}:TP={tp}:LRA={lra}:print_format=summary"
    raise ValueError("mode 只能是 dynaudnorm 或 loudnorm")


def audio_fade_in_out(fade_in: float = 2.5, fade_out: float = 2.8, total: float = 45.0,
                      curve: str = "tri", start_at: float = 0.0) -> str:
    """淡入淡出。返回可直接接在音轨后的 filter 链（out 的起点 = start_at+total-fade_out）。"""
    out_st = max(start_at, start_at + total - fade_out)
    parts = []
    if fade_in > 0:
        parts.append(f"afade=t=in:st={start_at}:d={fade_in}:curve={curve}")
    if fade_out > 0:
        parts.append(f"afade=t=out:st={out_st:.2f}:d={fade_out}:curve={curve}")
    return ",".join(parts)


# ---------------------------------------------------------------- 诊断
def _decode(path: str | Path, sr: int = SR) -> np.ndarray:
    """用 ffmpeg 解码成单声道 float32（16k），失败抛异常。"""
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
           "-f", "f32le", "-"]
    raw = subprocess.run(cmd, check=True, stdout=subprocess.PIPE).stdout
    return np.frombuffer(raw, dtype=np.float32)


def _envelope(x: np.ndarray, sr: int = SR, frame_ms: int = FRAME_MS) -> tuple[np.ndarray, np.ndarray]:
    n = max(1, int(sr * frame_ms / 1000))
    m = len(x) // n
    if m == 0:
        return np.array([0.0]), np.array([-90.0])
    frames = x[:m * n].reshape(m, n)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    db = 20 * np.log10(rms + 1e-9)
    t = np.arange(m) * frame_ms / 1000.0
    return t, db


def _resample_db(db: np.ndarray, n: int) -> np.ndarray:
    if len(db) == n:
        return db
    if len(db) == 0:
        return np.full(n, -90.0)
    idx = np.linspace(0, len(db) - 1, n)
    return np.interp(idx, np.arange(len(db)), db)


def audio_diagnose(voice_path: str | Path, bgm_path: str | Path | None = None,
                   speech_windows: list[list[float]] | None = None,
                   audible_db: float = -45.0, drop_db: float = -40.0,
                   min_gap: float = 0.4, is_mix: bool = False,
                   pause_max: float = 0.8, eaten_min: float = 1.5,
                   min_duck_db: float = 6.0) -> dict:
    """音频诊断（只看数值，不渲染）。

    speech_windows：已知有台词的区间 [[start,end],...]；不给时用能量自动检测。
    is_mix：bgm_path 传的是否为"已混好的成片音轨"。只有成片才有"压侧量"可谈；
            传独立 BGM 分轨时该指标无意义，不产生告警。
    空档分级（对台词窗口内的能量空档自动归类，减少人工复核负担）：
      duration <  pause_max (0.8s)  → pause  自然停顿，自动忽略，不产生告警
      <=          eaten_min (1.5s)  → gap    疑似吃字，warn 级人工复核
      >           eaten_min         → eaten  吃字（丢台词），block 级
    min_duck_db：is_mix=True 时台词段 BGM 侧链压低量的达标线（负向越深越好）。
    返回：
      bgm_entry_sec      BGM 首次可闻时间（>-45dBFS），用于发现"BGM 出场太晚"
      voice_db / bgm_db  台词段/非台词段的平均响度
      voice_bgm_diff     台词段内 人声dB - BGM dB（>6dB 才不容易被盖）
      ducking_db         台词段 BGM 相对非台词段的下降量（负值=确实压侧了；仅 is_mix 时告警）
      speech_drops       台词窗口内能量空档列表（兼容旧格式 [start, end, mean_db]）
      drop_detail        空档分级明细 {start,end,db,dur_sec,class}
      drop_summary       {pause, gap, eaten} 计数
      blocks             block 级结论（吃字=丢台词）
      flags              自动结论（warn/提示级）
    """
    v = _decode(voice_path)
    vt, vdb = _envelope(v)
    out = {"voice_file": str(voice_path), "duration": round(len(v) / SR, 2)}

    if speech_windows is None:
        floor = float(np.percentile(vdb, 15))
        thr = max(audible_db, floor + 8)
        active = vdb > thr
        speech_windows = []
        i = 0
        while i < len(active):
            if active[i]:
                j = i
                while j < len(active) and active[j]:
                    j += 1
                if (j - i) * FRAME_MS / 1000 >= 0.3:
                    speech_windows.append([round(vt[i], 2), round(vt[min(j, len(vt) - 1)], 2)])
                i = j
            else:
                i += 1
        out["auto_speech_windows"] = True
    else:
        out["auto_speech_windows"] = False
    out["speech_windows"] = speech_windows

    mask = np.zeros(len(vt), dtype=bool)
    for a, b in speech_windows:
        mask |= (vt >= a) & (vt <= b)
    out["voice_db"] = round(float(np.mean(vdb[mask])), 1) if mask.any() else None

    drops = []
    drop_detail = []
    counts = {"pause": 0, "gap": 0, "eaten": 0}
    for a, b in speech_windows:
        sel = (vt >= a) & (vt <= b)
        if not sel.any():
            continue
        d = vdb[sel]
        tt = vt[sel]
        quiet = d < drop_db
        i = 0
        while i < len(quiet):
            if quiet[i]:
                j = i
                while j < len(quiet) and quiet[j]:
                    j += 1
                dur = (j - i) * FRAME_MS / 1000.0
                if dur >= min_gap:
                    mean_db = round(float(np.mean(d[i:j])), 1)
                    start_t, end_t = round(float(tt[i]), 2), round(float(tt[j - 1]), 2)
                    drops.append([start_t, end_t, mean_db])
                    # 空档分级：<0.8s 自然停顿（忽略）；0.8~1.5s 疑似吃字；>1.5s 吃字（阻断）
                    cls = "pause" if dur < pause_max else ("gap" if dur <= eaten_min else "eaten")
                    counts[cls] += 1
                    drop_detail.append({"start": start_t, "end": end_t, "db": mean_db,
                                        "dur_sec": round(dur, 2), "class": cls})
                i = j
            else:
                i += 1
    out["speech_drops"] = drops
    out["drop_detail"] = drop_detail
    out["drop_summary"] = counts

    if bgm_path:
        b = _decode(bgm_path)
        bt, bdb = _envelope(b)
        bdb_r = _resample_db(bdb, len(vdb))
        on = np.where(bdb > audible_db)[0]
        out["bgm_file"] = str(bgm_path)
        out["bgm_entry_sec"] = round(float(bt[on[0]]), 2) if len(on) else None
        if mask.any():
            out["bgm_db_in_speech"] = round(float(np.mean(bdb_r[mask])), 1)
            out["voice_bgm_diff"] = round(float(np.mean(vdb[mask]) - np.mean(bdb_r[mask])), 1)
            out["ducking_db"] = round(float(np.mean(bdb_r[mask]) - np.mean(bdb_r[~mask])), 1) \
                if (~mask).any() else None
        else:
            out["bgm_db_in_speech"] = None

    flags = []
    blocks = []
    if out.get("bgm_entry_sec") is not None and out["bgm_entry_sec"] > 1.5:
        flags.append(f"BGM 入场偏晚（{out['bgm_entry_sec']}s）")
    if out.get("voice_bgm_diff") is not None and out["voice_bgm_diff"] < 6:
        flags.append(f"人声与 BGM 差距仅 {out['voice_bgm_diff']}dB，容易被盖")
    if out.get("ducking_db") is not None and is_mix and out["ducking_db"] > -min_duck_db:
        depth = round(-out["ducking_db"], 1)
        flags.append(f"台词段 BGM 仅压低 {depth}dB（未达 {min_duck_db}dB 目标），"
                     f"建议提高 ratio 或加深 bgm_gain_db")
    if counts["eaten"]:
        blocks.append(f"吃字空档（>{eaten_min}s）{counts['eaten']} 处：判定丢台词，"
                      f"必须换音频或调整切点（{[d['start'] for d in drop_detail if d['class'] == 'eaten']}）")
    if counts["gap"]:
        flags.append(f"疑似吃字空档（{pause_max}~{eaten_min}s）{counts['gap']} 处，需人工复核")
    if counts["pause"] and not counts["gap"] and not counts["eaten"]:
        flags.append(f"{counts['pause']} 处空档均为自然停顿（<{pause_max}s），自动忽略")
    out["flags"] = flags
    out["blocks"] = blocks
    return out


def report_md(report: dict) -> str:
    lines = ["# 音频诊断报告", "",
             "| 指标 | 值 |", "|---|---|"]
    for k in ("duration", "voice_db", "bgm_entry_sec", "bgm_db_in_speech",
              "voice_bgm_diff", "ducking_db", "auto_speech_windows"):
        if k in report:
            lines.append(f"| {k} | {report[k]} |")
    lines += ["", "## 台词窗口", "", "| start | end |", "|---|---|"]
    for a, b in report.get("speech_windows", []):
        lines.append(f"| {a} | {b} |")
    lines += ["", "## 空档分级", "", "| start | end | 平均dB | 时长s | 级别 |", "|---|---|---|---|---|"]
    for d in report.get("drop_detail", []):
        cls = {"pause": "自然停顿(忽略)", "gap": "疑似吃字(复核)", "eaten": "吃字(阻断)"}[d["class"]]
        lines.append(f"| {d['start']} | {d['end']} | {d['db']} | {d['dur_sec']} | {cls} |")
    if not report.get("drop_detail"):
        lines.append("| - | - | - | - | 无空档 |")
    lines += ["", "## 自动结论", ""]
    lines += [f"- [BLOCK] {b}" for b in report.get("blocks", [])]
    lines += [f"- {f}" for f in report.get("flags", [])]
    if not report.get("flags") and not report.get("blocks"):
        lines.append("- 无明显问题")
    return "\n".join(lines) + "\n"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="音频诊断（不渲染视频）")
    ap.add_argument("--voice", required=True)
    ap.add_argument("--bgm", default="")
    ap.add_argument("--speech", default="", help="台词窗口，如 22.55-24.35,30-33")
    ap.add_argument("--out", default="audio_diagnose.json")
    a = ap.parse_args()
    wins = None
    if a.speech:
        wins = [[float(x) for x in seg.split("-")] for seg in a.speech.split(",")]
    rep = audio_diagnose(a.voice, a.bgm or None, wins)
    Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
