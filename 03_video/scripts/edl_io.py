#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""edl_io.py — 内部时间轴 JSON ↔ CMX3600 EDL 最小读写（零第三方依赖）。

只覆盖"镜头切分"相关字段：
  TITLE / FCM / NNN  AX  V  C  src_in src_out rec_in rec_out / * FROM CLIP NAME
不支持：转场（D/W）、变速、多轨音频 EDL、59.94 丢帧时间码 —— 遇到直接报错，不静默丢数据。

内部时间轴两种输入都支持：
  1) timeline_45s.json 的 sections 结构（video / video_sequence）
  2) 扁平结构 {"segments":[{"source","src_in","dur","rec_in"}]}

用法：
  python edl_io.py --timeline timeline_45s.json --out demo.edl --fps 25
  python edl_io.py --read demo.edl --out timeline_from_edl.json --fps 25
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

TC_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})[:;](\d{2})$")
EVENT_RE = re.compile(
    r"^(\d{3,6})\s+(\S+)\s+(V|A|B|A2|AA)\s+(C|W\d*|D\d*|K|L/J)\s+"
    r"(\d{1,2}:\d{2}:\d{2}[:;]\d{2})\s+(\d{1,2}:\d{2}:\d{2}[:;]\d{2})\s+"
    r"(\d{1,2}:\d{2}:\d{2}[:;]\d{2})\s+(\d{1,2}:\d{2}:\d{2}[:;]\d{2})")


def tc_to_sec(tc: str, fps: float) -> float:
    m = TC_RE.match(tc.strip())
    if not m:
        raise ValueError(f"非法时间码：{tc}")
    h, mi, s, f = (int(x) for x in m.groups())
    return h * 3600 + mi * 60 + s + f / fps


def sec_to_tc(sec: float, fps: float) -> str:
    if sec < 0:
        raise ValueError("时间码不能为负")
    total_frames = int(round(sec * fps))
    f = total_frames % int(round(fps))
    total_s = total_frames // int(round(fps))
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def _clips(tl: dict) -> list[dict]:
    """把两种内部格式统一成 [{source, src_in, dur, rec_in}]。"""
    out = []
    if "sections" in tl:
        for sec in tl["sections"]:
            rec = float(sec.get("start", 0.0))
            vs = sec.get("video_sequence") or ([sec["video"]] if sec.get("video") else [])
            for v in vs:
                dur = float(v.get("dur", 0))
                if dur <= 0:
                    continue
                out.append({"source": Path(v.get("src", "")).name,
                            "src_in": float(v.get("in", 0)), "dur": dur, "rec_in": rec,
                            "note": sec.get("name", "")})
                rec += dur
    else:
        rec = 0.0
        for seg in tl.get("segments", []):
            dur = float(seg.get("dur", 0))
            if dur <= 0:
                continue
            out.append({"source": Path(seg.get("source", "")).name,
                        "src_in": float(seg.get("src_in", 0)), "dur": dur,
                        "rec_in": float(seg.get("rec_in", rec)), "note": seg.get("note", "")})
            rec = float(seg.get("rec_in", rec)) + dur
    return out


def timeline_to_edl(tl: dict, fps: float | None = None, title: str | None = None,
                    reel: str = "AX") -> str:
    fps = float(fps or tl.get("fps") or 25.0)
    title = title or Path(str(tl.get("project", "TIMELINE"))).stem or "TIMELINE"
    clips = _clips(tl)
    if not clips:
        raise ValueError("时间轴里没有可导出的镜头（video / video_sequence / segments 全为空）")
    lines = [f"TITLE:   {title}", "FCM: NON-DROP FRAME", ""]
    for i, c in enumerate(clips, 1):
        s0 = c["src_in"]
        s1 = s0 + c["dur"]
        r0 = c["rec_in"]
        r1 = r0 + c["dur"]
        lines.append(f"{i:03d}  {reel:<8} V     C        "
                     f"{sec_to_tc(s0, fps)} {sec_to_tc(s1, fps)} "
                     f"{sec_to_tc(r0, fps)} {sec_to_tc(r1, fps)}")
        lines.append(f"* FROM CLIP NAME: {c['source']}")
        if c.get("note"):
            lines.append(f"* COMMENT: {c['note']}")
    return "\n".join(lines) + "\n"


def edl_to_timeline(text: str, fps: float | None = None) -> dict:
    fps = float(fps or 25.0)
    title = "EDL"
    segments, pending = [], None
    seen_events = set()
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.upper().startswith("TITLE:"):
            title = line.split(":", 1)[1].strip() or "EDL"
            continue
        if "DROP FRAME" in line.upper() and "NON" not in line.upper():
            raise ValueError("不支持丢帧（DROP FRAME）时间码")
        m = EVENT_RE.match(line)
        if m:
            ev, reel, track, trans, si, so, ri, ro = m.groups()
            if trans != "C":
                raise ValueError(f"仅支持 C（cut）事件，遇到 {trans}：{line}")
            if track != "V":
                continue  # 同一事件的 A 轨行跳过（最小子集只保留视频）
            if ev in seen_events:
                continue
            seen_events.add(ev)
            a = tc_to_sec(si, fps)
            b = tc_to_sec(so, fps)
            r = tc_to_sec(ri, fps)
            pending = {"source": "", "src_in": round(a, 3), "dur": round(b - a, 3),
                       "rec_in": round(r, 3), "note": ""}
            segments.append(pending)
            continue
        if line.startswith("*") and pending is not None:
            up = line.upper()
            if "FROM CLIP NAME:" in up:
                pending["source"] = line.split(":", 1)[1].strip()
            elif "COMMENT:" in up:
                pending["note"] = line.split(":", 1)[1].strip()
    if not segments:
        raise ValueError("没有解析到任何 C 事件")
    total = max(s["rec_in"] + s["dur"] for s in segments)
    return {"title": title, "fps": fps, "duration": round(total, 3), "segments": segments}


def main() -> int:
    ap = argparse.ArgumentParser(description="内部时间轴 ↔ CMX3600 EDL")
    ap.add_argument("--timeline", default="")
    ap.add_argument("--read", default="")
    ap.add_argument("--fps", type=float, default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    if a.read:
        tl = edl_to_timeline(Path(a.read).read_text(encoding="utf-8", errors="ignore"), a.fps)
        Path(a.out).write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"EDL -> timeline: {len(tl['segments'])} clips, {tl['duration']}s -> {a.out}")
        return 0
    if not a.timeline:
        ap.error("需要 --timeline 或 --read")
    tl = json.loads(Path(a.timeline).read_text(encoding="utf-8"))
    edl = timeline_to_edl(tl, a.fps)
    Path(a.out).write_text(edl, encoding="utf-8")
    print(f"timeline -> EDL: {edl.count(' FROM CLIP NAME')} clips -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
