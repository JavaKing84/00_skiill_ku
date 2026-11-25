#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_narrative.py — 叙事连贯性 / J-cut 分级校验（block / warn）。

解决旧版 validate_45s.py 的三个缺口：
  1. 无法根据镜头语义 JSON 校验"景别—情绪"是否匹配；
  2. J-cut（画外人声）要么静默通过、要么一刀切报错，没有分级；
  3. 没有区分"必须重剪"（block）和"可人工放行"（warn）。

输入：
  --timeline   结构化时间轴 JSON（兼容 assets/elephant/build45/timeline_45s.json 的 sections 结构）
  --shots      可选，shot_analyze.py 输出 JSON（用于景别一致性抽查）
  --forbidden  可选，禁止支线区间 JSON：[{"name":"枪","src":"导剪001.mp4","start":1008,"end":1032}]
  --emotion-script  情绪递进脚本，逗号分隔，默认 "压抑,挣扎,对峙,放空,压抑"
  --allow-jcut / --no-allow-jcut   J-cut 是告警还是阻断（默认 allow）

输出 JSON：{"verdict","counts","issues":[{"error_level","message","time_range"}]}
退出码：0=PASS/WARN，1=存在 block。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_EMOTIONS = ["压抑", "挣扎", "对峙", "放空", "压抑"]
SHORT_SHOT_SEC = 1.2
SHORT_RATIO_WARN = 0.40
LONG_SHOT_SEC = 25.0


def _segments(tl: dict) -> list[dict]:
    """把 sections 展平成带 src/in/dur/role/emotion 的片段列表。"""
    out = []
    for sec in tl.get("sections", []):
        vs = sec.get("video_sequence")
        if vs:
            for v in vs:
                out.append({"sid": sec["id"], "src": Path(v.get("src", "")).name,
                            "in": float(v.get("in", 0)), "dur": float(v.get("dur", 0)),
                            "role": v.get("role") or sec.get("role"),
                            "emotion": sec.get("emotion"),
                            "declared_scale": v.get("scale") or sec.get("shot"),
                            "audio_type": (sec.get("audio") or {}).get("type"),
                            "audio_speaker": (sec.get("audio") or {}).get("speaker")
                                             or (sec.get("audio") or {}).get("role")})
        else:
            v = sec.get("video") or {}
            if not v:
                continue
            out.append({"sid": sec["id"], "src": Path(v.get("src", "")).name,
                        "in": float(v.get("in", 0)), "dur": float(v.get("dur", 0)),
                        "role": sec.get("role"), "emotion": sec.get("emotion"),
                        "declared_scale": sec.get("shot"),
                        "audio_type": (sec.get("audio") or {}).get("type"),
                        "audio_speaker": (sec.get("audio") or {}).get("speaker")
                                         or (sec.get("audio") or {}).get("role")})
    return out


def check_emotion(tl: dict, script: list[str]) -> list[dict]:
    issues = []
    seq = [s.get("emotion") for s in tl.get("sections", []) if s.get("emotion")]
    if not seq:
        return [{"error_level": "warn", "message": "时间轴没有 emotion 字段，跳过情绪顺序校验",
                 "time_range": "-"}]
    # 允许重复：按脚本顺序做"非递减"子序列匹配。
    # 脚本中同一情绪可出现多次（如 压抑 同时在 script[0] 与 script[-1]，构成环形收束）。
    # 旧实现用单调递增的 i 只把脚本消费一遍，导致连续同情绪（如压抑×6）在第 3 个就
    # 无处匹配而误报 block；此处改为记录"最后匹配到的脚本位置 last"，同情绪可连续占槽
    # （停在同一位置），只能向前推进、不能回退，脚本末尾复用的情绪在推进到末尾后仍可匹配。
    pos_of: dict[str, list[int]] = {}
    for idx, e in enumerate(script):
        pos_of.setdefault(e, []).append(idx)
    last = -1
    for n, emo in enumerate(seq):
        idxs = pos_of.get(emo)
        if not idxs:
            issues.append({"error_level": "block",
                           "message": f"情绪顺序不符合脚本：出现 '{emo}'（不在脚本 {'→'.join(script)} 中）",
                           "time_range": f"{n}"})
            break
        nxt = [p for p in idxs if p >= last]
        if not nxt:
            issues.append({"error_level": "block",
                           "message": f"情绪顺序不符合脚本：出现 '{emo}'，脚本为 {'→'.join(script)}",
                           "time_range": f"{n}"})
            break
        last = nxt[0]
    # 首尾锚点抽查
    if seq[0] != script[0]:
        issues.append({"error_level": "warn",
                       "message": f"开场情绪 '{seq[0]}' 与脚本开篇 '{script[0]}' 不一致",
                       "time_range": "0.00"})
    if seq[-1] != script[-1]:
        issues.append({"error_level": "warn",
                       "message": f"收尾情绪 '{seq[-1]}' 与脚本收尾 '{script[-1]}' 不一致",
                       "time_range": "结尾"})
    return issues


def check_jcut(tl: dict, allow_jcut: bool) -> list[dict]:
    issues = []
    for sec in tl.get("sections", []):
        audio = sec.get("audio") or {}
        atype = str(audio.get("type", ""))
        vs = sec.get("video_sequence") or ([sec.get("video")] if sec.get("video") else [])
        video_roles = {v.get("role") for v in vs if v.get("role")}
        speaker = audio.get("speaker") or audio.get("role")
        same_src = all(Path(v.get("src", "")).name == Path(audio.get("src", "")).name
                       for v in vs if v.get("src") and audio.get("src"))
        is_vo = any(k in atype for k in ("V.O.", "VO", "独白", "画外"))
        speaker_mismatch = bool(speaker and video_roles and speaker not in video_roles)
        if is_vo or speaker_mismatch or not same_src:
            detail = []
            if is_vo:
                detail.append(f"音频类型={atype}")
            if speaker_mismatch:
                detail.append(f"说话人={speaker} 画面={sorted(video_roles)}")
            if not same_src:
                detail.append("音画不同源")
            issues.append({
                "error_level": "warn" if allow_jcut else "block",
                "message": f"J-cut：{sec['id']} " + "；".join(detail),
                "time_range": f"{sec.get('start', 0):.2f}-{sec.get('start', 0) + sec.get('dur', 0):.2f}",
            })
    return issues


def check_forbidden(tl: dict, forbidden: list[dict]) -> list[dict]:
    issues = []
    if not forbidden:
        return issues
    for seg in _segments(tl):
        a, b = seg["in"], seg["in"] + seg["dur"]
        for fb in forbidden:
            if Path(fb.get("src", "")).name != seg["src"]:
                continue
            if b <= fb["start"] or a >= fb["end"]:
                continue
            issues.append({
                "error_level": "block",
                "message": f"命中禁止支线【{fb.get('name', '未命名')}】：{seg['sid']} {seg['src']} {a:.2f}-{b:.2f}",
                "time_range": f"{a:.2f}-{b:.2f}",
            })
    return issues


def check_rhythm(tl: dict) -> tuple[list[dict], dict]:
    issues = []
    segs = _segments(tl)
    durs = [s["dur"] for s in segs if s["dur"] > 0]
    if not durs:
        return issues, {}
    short = [d for d in durs if d < SHORT_SHOT_SEC]
    long_ = [d for d in durs if d >= LONG_SHOT_SEC]
    short_ratio = len(short) / len(durs)
    stats = {"segments": len(durs), "short_ratio": round(short_ratio, 3),
             "max_dur": round(max(durs), 2), "total_dur": round(sum(durs), 2)}
    if short_ratio > SHORT_RATIO_WARN:
        issues.append({"error_level": "warn",
                       "message": f"碎镜头过多：{len(short)}/{len(durs)} 段短于 {SHORT_SHOT_SEC}s"
                                  f"（占比 {short_ratio:.0%}，阈值 {SHORT_RATIO_WARN:.0%}）",
                       "time_range": "-"})
    if long_:
        issues.append({"error_level": "warn",
                       "message": f"存在超长镜头：{len(long_)} 段 ≥ {LONG_SHOT_SEC}s，确认是否为叙事需要",
                       "time_range": "-"})
    return issues, stats


def check_scale_consistency(tl: dict, shots: list[dict]) -> list[dict]:
    issues = []
    if not shots:
        return issues
    for seg in _segments(tl):
        declared = seg.get("declared_scale") or ""
        if not declared or "→" in declared or "交叉" in declared:
            continue
        overlap = [s for s in shots
                   if Path(s.get("source", "")).name == seg["src"]
                   and min(s["end_time"], seg["in"] + seg["dur"]) - max(s["start_time"], seg["in"]) > 0.5 * seg["dur"]]
        if not overlap:
            continue
        best = max(overlap, key=lambda s: s["duration"])
        if best["shot_scale"] not in declared:
            issues.append({"error_level": "warn",
                           "message": f"景别标注不一致：{seg['sid']} 标注『{declared}』，"
                                      f"实测『{best['shot_scale']}』(人脸占比 {best['face_area_ratio']:.3f})",
                           "time_range": f"{seg['in']:.2f}-{seg['in'] + seg['dur']:.2f}"})
    return issues


def validate(tl: dict, shots: list[dict] | None = None, forbidden: list[dict] | None = None,
             emotion_script: list[str] | None = None, allow_jcut: bool = True) -> dict:
    script = emotion_script or DEFAULT_EMOTIONS
    issues = []
    issues += check_emotion(tl, script)
    issues += check_jcut(tl, allow_jcut)
    issues += check_forbidden(tl, forbidden or [])
    r_issues, stats = check_rhythm(tl)
    issues += r_issues
    issues += check_scale_consistency(tl, shots or [])

    blocks = [i for i in issues if i["error_level"] == "block"]
    warns = [i for i in issues if i["error_level"] == "warn"]
    return {
        "verdict": "FAIL" if blocks else ("WARN" if warns else "PASS"),
        "counts": {"block": len(blocks), "warn": len(warns)},
        "allow_jcut": allow_jcut,
        "emotion_script": script,
        "rhythm": stats,
        "issues": issues,
    }


def render_md(report: dict, title: str = "叙事校验报告") -> str:
    lines = [f"# {title}", "",
             f"- 结论：**{report['verdict']}**（block {report['counts']['block']} / warn {report['counts']['warn']}）",
             f"- allow_jcut：{report['allow_jcut']}",
             f"- 节奏统计：{json.dumps(report.get('rhythm', {}), ensure_ascii=False)}", "",
             "| 级别 | 时间范围 | 说明 |", "|---|---|---|"]
    for i in report["issues"]:
        lines.append(f"| {i['error_level']} | {i['time_range']} | {i['message']} |")
    if not report["issues"]:
        lines.append("| - | - | 无问题 |")
    lines += ["", "> block = 必须重剪；warn = 可人工确认后放行。"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="叙事连贯性/J-cut 分级校验")
    ap.add_argument("--timeline", required=True)
    ap.add_argument("--shots", default="")
    ap.add_argument("--forbidden", default="")
    ap.add_argument("--emotion-script", default=",".join(DEFAULT_EMOTIONS))
    ap.add_argument("--allow-jcut", dest="allow_jcut", action="store_true", default=True)
    ap.add_argument("--no-allow-jcut", dest="allow_jcut", action="store_false")
    ap.add_argument("--out", default="validate_narrative_report.json")
    ap.add_argument("--md", default="")
    a = ap.parse_args()

    tl = json.loads(Path(a.timeline).read_text(encoding="utf-8"))
    shots = json.loads(Path(a.shots).read_text(encoding="utf-8")) if a.shots else None
    forbidden = json.loads(Path(a.forbidden).read_text(encoding="utf-8")) if a.forbidden else None
    script = [x.strip() for x in a.emotion_script.split(",") if x.strip()]

    rep = validate(tl, shots, forbidden, script, a.allow_jcut)
    Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.md:
        Path(a.md).write_text(render_md(rep), encoding="utf-8")
    print(json.dumps(rep["counts"], ensure_ascii=False), "verdict=", rep["verdict"])
    for i in rep["issues"]:
        print(f"  [{i['error_level']}] {i['time_range']} {i['message']}")
    return 0 if rep["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
