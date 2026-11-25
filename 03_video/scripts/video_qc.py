#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video_qc.py — 成片质检（Phase 2.4，v2 增加时长守卫/冻结/静音检测）。

不能只看渲染退出码。检查：容器/编码/时长/画幅/帧率/音轨、首中尾帧、
黑屏段、静音段、画面冻结段、音量峰值与均值；
若提供 --plan-json（montage_edit.py 的报告）或 --plan-duration，
则校验"成片实际时长 vs 计划时长"，偏差超容差即 FAIL——
专治两类怪片：几秒桥段被拉长、只剪了前几秒就收工。
输出 video_qc_report.md 与机器可读 JSON。
退出码：0=全部通过；1=有 WARN 级问题；2=有 FAIL 级问题。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
from skillkit.media import ffprobe, summarize, blackdetect, volumedetect, extract_frames  # noqa: E402

# 短视频默认验收阈值（可被参数覆盖）
DEFAULTS = {
    "min_duration": 3.0,
    "max_duration": 600.0,
    "min_height": 480,
    "allowed_fps": {24, 25, 30, 50, 60},
    "max_black_seconds": 1.5,
    "silent_max_volume_db": -45.0,   # 峰值低于此值视为无声
    "peak_ceiling_db": -0.5,         # 峰值高于此值视为爆音风险
    "duration_tolerance": 1.0,       # 成片 vs 计划时长最大偏差（秒）
    "max_freeze_seconds": 3.0,       # 画面冻结累计上限（秒）
    "max_silence_seconds": 6.0,      # 静音累计上限（秒）
}


def _filter_scan(path: Path, expr: str, audio: bool = False) -> list[str]:
    """跑一遍 ffmpeg 滤镜，返回 stderr 行（用于解析检测器输出）。

    audio=True 时必须走 -af：silencedetect 是音频滤镜，用 -vf 会直接报
    "Filtergraph has a audio output, cannot connect it to video output stream"，
    导致静音段永远检测为空。
    """
    flag = "-af" if audio else "-vf"
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         flag, expr, "-f", "null", "-"],
        capture_output=True, text=True, timeout=900, encoding="utf-8", errors="replace",
    )
    return (p.stderr or "").splitlines()


def freezedetect(path: Path, min_duration: float = 2.0, noise: float = 0.003,
                 total_duration: float = 0.0) -> list[dict]:
    """检测画面冻结（几乎不变的帧）。返回 [{start, end, duration}]。

    冻结持续到片尾时 ffmpeg 只发 freeze_start 不发 freeze_end，
    必须用总片长闭合，否则"整段静止被拉长"的怪片会被漏判。
    """
    spans, cur_start = [], None
    for line in _filter_scan(path, f"freezedetect=n={noise}:d={min_duration}"):
        if "freeze_start" in line:
            m = re.search(r"freeze_start:\s*([\d.]+)", line)
            if m:
                cur_start = float(m.group(1))
        elif "freeze_end" in line and cur_start is not None:
            m = re.search(r"freeze_end:\s*([\d.]+)", line)
            if m:
                end = float(m.group(1))
                spans.append({"start": cur_start, "end": end,
                              "duration": round(end - cur_start, 2)})
                cur_start = None
    if cur_start is not None:
        end = total_duration if total_duration > cur_start else cur_start + min_duration
        spans.append({"start": cur_start, "end": end,
                      "duration": round(end - cur_start, 2)})
    return spans


def silencedetect(path: Path, min_duration: float = 2.0, noise_db: float = -50.0,
                  total_duration: float = 0.0) -> list[dict]:
    """检测静音段。返回 [{start, end, duration}]。同样闭合持续到片尾的静音。"""
    spans, cur_start = [], None
    for line in _filter_scan(path, f"silencedetect=noise={noise_db}dB:d={min_duration}", audio=True):
        if "silence_start" in line:
            m = re.search(r"silence_start:\s*(-?[\d.]+)", line)
            if m:
                cur_start = float(m.group(1))
        elif "silence_end" in line and cur_start is not None:
            m = re.search(r"silence_end:\s*(-?[\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)", line)
            if m:
                end, d = float(m.group(1)), float(m.group(2))
                spans.append({"start": max(0.0, cur_start), "end": end,
                              "duration": round(d, 2)})
                cur_start = None
    if cur_start is not None:
        end = total_duration if total_duration > cur_start else cur_start + min_duration
        spans.append({"start": max(0.0, cur_start), "end": end,
                      "duration": round(end - cur_start, 2)})
    return spans


def judge(meta: dict, blacks: list[dict], volume: dict, cfg: dict,
          freezes: list[dict] | None = None, silences: list[dict] | None = None,
          plan_duration: float | None = None) -> list[dict]:
    findings = []
    v, a = meta.get("video"), meta.get("audio")
    dur = meta.get("duration_seconds") or 0

    if not v:
        findings.append(("FAIL", "无视频流"))
    else:
        if v["height"] and v["height"] < cfg["min_height"]:
            findings.append(("FAIL", f"分辨率高度 {v['height']} < {cfg['min_height']}"))
        if v["fps"] and round(v["fps"]) not in cfg["allowed_fps"]:
            findings.append(("WARN", f"非常规帧率 {v['fps']}"))
    if not a:
        findings.append(("WARN", "无音轨（若为有意静音请人工确认）"))
    if not (cfg["min_duration"] <= dur <= cfg["max_duration"]):
        findings.append(("FAIL", f"时长 {dur}s 超出 [{cfg['min_duration']},{cfg['max_duration']}]"))

    # 时长守卫：成片 vs 计划。防"只剪前几秒"与"被拉长"
    if plan_duration and plan_duration > 0:
        dev = abs(dur - plan_duration)
        if dev > cfg["duration_tolerance"]:
            findings.append(("FAIL",
                             f"时长守卫：成片 {dur}s 偏离计划 {plan_duration}s 达 {dev:.2f}s "
                             f"(> {cfg['duration_tolerance']}s)，疑似偷懒截断或人为拉长"))
        else:
            findings.append(("INFO", f"时长守卫通过：成片 {dur}s ≈ 计划 {plan_duration}s"))

    black_total = round(sum(b.get("duration", 0) for b in blacks), 3)
    if black_total > cfg["max_black_seconds"]:
        findings.append(("WARN", f"黑屏累计 {black_total}s 超阈值 {cfg['max_black_seconds']}s"))

    if freezes is not None:
        freeze_total = round(sum(f.get("duration", 0) for f in freezes), 2)
        if freeze_total > cfg["max_freeze_seconds"]:
            findings.append(("FAIL",
                             f"画面冻结累计 {freeze_total}s 超阈值 {cfg['max_freeze_seconds']}s"
                             f"（冻结段：{freezes[:3]}），疑似素材不足被拉长"))
        elif freezes:
            findings.append(("INFO", f"少量冻结 {freeze_total}s（≤ {cfg['max_freeze_seconds']}s，放行）"))

    if silences is not None and a:
        silence_total = round(sum(s.get("duration", 0) for s in silences), 2)
        if silence_total > cfg["max_silence_seconds"]:
            findings.append(("WARN", f"静音累计 {silence_total}s 超阈值 {cfg['max_silence_seconds']}s"))

    if a:
        peak = volume.get("max_volume")
        mean = volume.get("mean_volume")
        if peak is not None and peak < cfg["silent_max_volume_db"]:
            findings.append(("FAIL", f"峰值 {peak}dB 低于 {cfg['silent_max_volume_db']}dB，疑似无声"))
        if peak is not None and peak > cfg["peak_ceiling_db"]:
            findings.append(("WARN", f"峰值 {peak}dB 高于 {cfg['peak_ceiling_db']}dB，爆音风险"))
        if mean is not None and mean < -35:
            findings.append(("WARN", f"均值 {mean}dB 过低，整体偏小声"))
    return [{"level": lvl, "message": msg} for lvl, msg in findings]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--plan-json", default="",
                    help="montage_edit.py 报告 JSON（含 planned_duration），用于时长守卫")
    ap.add_argument("--plan-duration", type=float, default=0.0,
                    help="直接给定计划时长（秒）；与 --plan-json 二选一")
    ap.add_argument("--tolerance", type=float, default=0.0,
                    help="时长守卫容差（秒），默认取内置 1.0")
    ap.add_argument("--max-freeze", type=float, default=0.0,
                    help="画面冻结累计上限（秒），默认取内置 3.0；"
                         "固定机位空镜多文艺片项目可显式放宽（冻结事实仍完整记录）")
    args = ap.parse_args()
    video = Path(args.video)
    if not video.exists():
        print(f"FAIL: {video} not found", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = dict(DEFAULTS)
    if args.tolerance > 0:
        cfg["duration_tolerance"] = args.tolerance
    if args.max_freeze > 0:
        cfg["max_freeze_seconds"] = args.max_freeze

    plan_duration = args.plan_duration
    if not plan_duration and args.plan_json:
        plan_path = Path(args.plan_json)
        if plan_path.exists():
            try:
                pdata = json.loads(plan_path.read_text(encoding="utf-8"))
                plan_duration = float(pdata.get("planned_duration") or 0)
            except (json.JSONDecodeError, ValueError):
                pass

    meta = summarize(ffprobe(video))
    dur = meta["duration_seconds"] or 0
    blacks = blackdetect(video)
    volume = volumedetect(video) if meta.get("audio") else {"mean_volume": None, "max_volume": None}
    freezes = freezedetect(video, min_duration=2.0, total_duration=dur)
    silences = silencedetect(video, min_duration=2.0, total_duration=dur) if meta.get("audio") else []
    stamps = sorted({0.0, round(dur / 2, 3), max(0.0, dur - 0.1)})
    frames = extract_frames(video, stamps, out / "qc_frames")
    findings = judge(meta, blacks, volume, cfg, freezes, silences, plan_duration or None)
    verdict_fail = any(f["level"] == "FAIL" for f in findings)

    result = {
        "schema": "video-qc-v2",
        "video": str(video),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "probe": meta,
        "plan_duration": plan_duration or None,
        "black_spans": blacks,
        "freeze_spans": freezes,
        "silence_spans": silences,
        "volume": volume,
        "frames": [str(p) for p in frames],
        "findings": findings,
        "verdict": "FAIL" if verdict_fail
        else ("WARN" if any(f["level"] == "WARN" for f in findings) else "PASS"),
    }
    (out / "video_qc.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 视频质检报告 — {video.name}",
        f"- 检查时间：{result['checked_at']}",
        f"- 结论：**{result['verdict']}**",
        f"- 容器/时长：{meta['container']} / {dur}s"
        + (f"（计划 {plan_duration}s，偏差 {abs(dur - plan_duration):.2f}s）" if plan_duration else ""),
        f"- 视频：{meta['video']}",
        f"- 音频：{meta['audio']}",
        f"- 黑屏段：{blacks or '无'}",
        f"- 冻结段：{freezes or '无'}",
        f"- 静音段：{silences or '无'}",
        f"- 音量：{volume}",
        f"- 抽帧（首/中/尾）：{[p.name for p in frames]}",
        "",
        "## 问题清单",
    ]
    lines += [f"- [{f['level']}] {f['message']}" for f in findings] or ["- 无"]
    (out / "video_qc_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"QC {result['verdict']} -> {out / 'video_qc_report.md'}")
    return 0 if result["verdict"] == "PASS" else (1 if result["verdict"] == "WARN" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
