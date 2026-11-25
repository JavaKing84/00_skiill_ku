#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quality_check_all.py — 成片质量综合巡检统一入口（纯分析，绝不渲染 mp4）。

把此前七个模块串成一条流水线：读「素材目录 + 剪辑时间轴 JSON」，一次性跑完
  1) 人物出镜核查（person_scan：目标主角 / 黑名单人物）
  2) 镜头语义与节奏（shot_analyze：景别 / motion / 长短镜头）
  3) 叙事顺序 + J-cut 分级 + 禁支线命中（validate_narrative）
  4) 音频指标（audio_skill.audio_diagnose：台词响度 / 丢台词空档 / BGM 电平）
  5) 素材边界（ffprobe：in+dur 是否越界）

输出：
  <outdir>/quality_report.md    人读综合报告（借鉴 continuityguard-cli 的排版思路）
  <outdir>/quality_report.json  机器可读全量数据

退出码：0=PASS，1=WARN，2=FAIL（有 block 级问题）
注意：本脚本只做分析与报告，不生成任何视频文件。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audio_skill import audio_diagnose  # noqa: E402
from person_scan import FaceEngine, load_gallery, scan  # noqa: E402
from shot_analyze import analyze as analyze_shots  # noqa: E402
from validate_narrative import DEFAULT_EMOTIONS, render_md as render_narrative_md, validate  # noqa: E402


# ------------------------------------------------------------------ 时间轴解析
def sections_of(tl: dict) -> list[dict]:
    """把 sections 归一成 {id,name,start,dur,emotion,clips:[{src,in,dur,role,scale}],audio}。"""
    out = []
    for sec in tl.get("sections", []):
        vs = sec.get("video_sequence")
        clips = []
        if vs:
            for v in vs:
                clips.append({"src": v.get("src", ""), "in": float(v.get("in", 0)),
                              "dur": float(v.get("dur", 0)),
                              "role": v.get("role") or sec.get("role"),
                              "scale": v.get("scale") or sec.get("shot")})
        elif sec.get("video"):
            v = sec["video"]
            clips.append({"src": v.get("src", ""), "in": float(v.get("in", 0)),
                          "dur": float(v.get("dur", 0)),
                          "role": sec.get("role"), "scale": sec.get("shot")})
        audio = sec.get("audio") or {}
        out.append({"id": sec.get("id", "?"), "name": sec.get("name", ""),
                    "start": float(sec.get("start", 0)), "dur": float(sec.get("dur", 0)),
                    "emotion": sec.get("emotion"), "clips": clips,
                    "audio": {"src": audio.get("src", ""), "in": float(audio.get("in", 0)),
                              "dur": float(audio.get("dur", 0)),
                              "type": str(audio.get("type", "")),
                              "speaker": audio.get("speaker") or audio.get("role"),
                              "text": audio.get("text", "")}})
    return out


def probe_duration(path: Path) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)],
                       capture_output=True, text=True)
    try:
        return float((p.stdout or "").strip() or 0.0)
    except ValueError:
        return 0.0


def extract_wav(video: Path, start: float, dur: float, out: Path) -> bool:
    p = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
                        "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(out)],
                       capture_output=True, text=True)
    return p.returncode == 0 and out.exists() and out.stat().st_size > 1000


# ------------------------------------------------------------------ 单项检查
def check_person(secs: list[dict], video_dir: Path, gallery_dir: Path,
                 fps: float = 1.0) -> tuple[list[dict], list[dict]]:
    """逐段逐片段扫描画面人物；返回 (段落级汇总, 明细窗口)。"""
    gal = load_gallery(gallery_dir, FaceEngine(0.7, 0.3))
    summary, details = [], []
    for sec in secs:
        targets, blacks, conf, faces, windows = set(), set(), 0.0, 0, 0
        for c in sec["clips"]:
            vp = video_dir / c["src"]
            if not vp.exists() or c["dur"] <= 0:
                continue
            win = max(1.0, min(4.0, c["dur"]))
            rows, det = scan(vp, c["in"], c["in"] + c["dur"], gal, window=win,
                             fps=fps, min_face_px=48)
            windows += len(rows)
            for d in det:
                targets.update(d.get("targets", {}))
                blacks.update(d.get("blacklist", {}))
                conf = max(conf, float(d.get("max_similarity", 0)))
                faces = max(faces, int(d.get("face_count", 0)))
                details.append({"section": sec["id"], "src": c["src"],
                                "start": d["start"], "end": d["end"],
                                "targets": d.get("targets", {}),
                                "blacklist": d.get("blacklist", {})})
        summary.append({"section": sec["id"], "name": sec["name"],
                        "target": sorted(targets), "blacklist": sorted(blacks),
                        "face_count": faces, "confidence": round(conf, 3),
                        "windows": windows,
                        "verdict": "blacklist" if blacks else ("target" if targets else "nobody")})
    return summary, details


def check_shots(secs: list[dict], video_dir: Path, fps: float = 2.0) -> list[dict]:
    shots = []
    for sec in secs:
        for c in sec["clips"]:
            vp = video_dir / c["src"]
            if not vp.exists() or c["dur"] <= 0:
                continue
            shots += analyze_shots(vp, c["in"], c["in"] + c["dur"], sample_fps=fps)
    return shots


def check_audio(secs: list[dict], video_dir: Path, tmp: Path) -> list[dict]:
    out = []
    for sec in secs:
        a = sec["audio"]
        item = {"section": sec["id"], "type": a["type"], "voice_db": None,
                "speech_drops": [], "drop_summary": {}, "flags": [], "skip": ""}
        if not a["src"]:
            item["skip"] = "该段无独立音频源（交给 BGM/静音）"
            out.append(item)
            continue
        vp = video_dir / a["src"]
        if not vp.exists():
            item["skip"] = f"音频源不存在：{a['src']}"
            out.append(item)
            continue
        wav = tmp / f"a_{sec['id']}.wav"
        if not extract_wav(vp, a["in"], a["dur"], wav):
            item["skip"] = "音频抽取失败（区间越界或无声轨）"
            out.append(item)
            continue
        rep = audio_diagnose(wav, None, [[0.0, round(a["dur"], 2)]])
        item.update({"voice_db": rep.get("voice_db"),
                     "speech_drops": rep.get("speech_drops", []),
                     "drop_summary": rep.get("drop_summary", {}),
                     "drop_detail": rep.get("drop_detail", []),
                     "flags": rep.get("flags", [])})
        out.append(item)
    return out


def check_bgm(bgm: Path, tl: dict, audio_rows: list[dict]) -> dict:
    """BGM 电平估算：不渲染，用「原声轨实测 dB」对比「BGM 原始 dB + 计划增益 + 侧链压低」估算遮盖风险。

    时间轴 audio_plan.bgm 声明了 ducking 配置时，估算差按 duck_depth_db（默认 8dB，
    即 sidechaincompress threshold=0.03/ratio=9 在台词段的实测压低档位）计入有效差；
    渲染后由 montage_edit.measure_duck / audio_diagnose(is_mix=True) 实测闭环。
    """
    plan = ((tl.get("audio_plan") or {}).get("bgm") or {})
    gain = float(plan.get("gain_db", 0.0))
    duck_depth = float(plan.get("duck_depth_db", 8.0)) if plan.get("ducking") else 0.0
    if not bgm or not bgm.exists():
        return {"file": str(bgm) if bgm else "", "skip": "未提供 BGM"}
    dur = probe_duration(bgm)
    wav = Path(tempfile.mkdtemp(prefix="bgmchk_")) / "bgm.wav"
    if not extract_wav(bgm, 0.0, max(0.5, min(dur, 600.0)), wav):
        return {"file": str(bgm), "skip": "BGM 解码失败"}
    rep = audio_diagnose(wav, None, [[0.0, max(0.5, min(dur, 600.0))]])
    bgm_db = rep.get("voice_db")
    rows = [{"section": r["section"], "voice_db": r["voice_db"],
             "bgm_est_db": None if bgm_db is None else round(bgm_db + gain, 1),
             "est_diff_db": None if (bgm_db is None or r["voice_db"] is None)
             else round(r["voice_db"] - (bgm_db + gain), 1)}
            for r in audio_rows if r.get("voice_db") is not None]
    for row in rows:
        row["duck_depth_db"] = duck_depth
        row["eff_diff_db"] = (None if row["est_diff_db"] is None
                              else round(row["est_diff_db"] + duck_depth, 1))
    return {"file": str(bgm), "duration": round(dur, 2), "bgm_mean_db": bgm_db,
            "planned_gain_db": gain, "duck_depth_db": duck_depth,
            "planned_entry_sec": plan.get("from"),
            "planned_fade_in": plan.get("fade_in"),
            "planned_fade_out": plan.get("fade_out"),
            "per_section": rows,
            "note": "估算值：= 原声实测dB − (BGM原始dB + 计划增益)；eff=估算差+侧链压低(duck_depth_db)，"
                    "eff ≥6dB 才不易被盖；真实混音以渲染后 audio_diagnose(is_mix=True) 实测为准。"}


def check_bounds(secs: list[dict], video_dir: Path) -> list[dict]:
    cache: dict[str, float] = {}
    issues = []
    for sec in secs:
        for c in sec["clips"]:
            if c["src"] not in cache:
                vp = video_dir / c["src"]
                cache[c["src"]] = probe_duration(vp) if vp.exists() else 0.0
            total = cache[c["src"]]
            if total <= 0:
                issues.append({"section": sec["id"], "src": c["src"],
                               "level": "block", "message": "素材文件不存在或无法读取"})
                continue
            end = c["in"] + c["dur"]
            if end > total + 0.05:
                issues.append({"section": sec["id"], "src": c["src"], "level": "block",
                               "message": f"越界：in+dur={end:.2f}s > 源时长 {total:.2f}s"})
    return issues


# ------------------------------------------------------------------ 汇总
def run(timeline: Path, video_dir: Path, gallery: Path, outdir: Path,
        forbidden: list[dict] | None = None, emotion_script: list[str] | None = None,
        allow_jcut: bool = True, bgm: Path | None = None,
        blacklist_level: str = "block", fps_person: float = 1.0,
        fps_shot: float = 2.0, skip_person: bool = False,
        skip_shot: bool = False, blacklist_buffer: float = 5.0) -> dict:
    tl = json.loads(timeline.read_text(encoding="utf-8"))
    secs = sections_of(tl)
    outdir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="qaall_"))

    # 黑名单/禁支线窗口 ±N 秒避让缓冲（敏感人物如王金），只作用于画面（视频片段），
    # 音频画外 VO 不受影响（符合"画面严格过滤、允许画外音"的规则）。
    forbidden_eff = []
    for fb in forbidden or []:
        s, e = float(fb.get("start", -1)), float(fb.get("end", -1))
        if s < 0 or e <= s:                     # 区间未掌握（如枪支线 -1）：保持禁用原样
            forbidden_eff.append(dict(fb))
            continue
        b = float(fb.get("buffer", blacklist_buffer))
        forbidden_eff.append({**fb, "orig_start": s, "orig_end": e,
                              "start": max(0.0, s - b), "end": e + b, "buffer": b})

    person, person_detail = ([], [])
    if not skip_person:
        person, person_detail = check_person(secs, video_dir, gallery, fps_person)
    shots = [] if skip_shot else check_shots(secs, video_dir, fps_shot)
    audio_rows = check_audio(secs, video_dir, tmp)
    bgm_info = check_bgm(bgm, tl, audio_rows)
    bounds = check_bounds(secs, video_dir)

    narrative = validate(tl, shots, forbidden_eff, emotion_script, allow_jcut)

    # 黑名单出镜 → 可配置为 block（默认）或 warn
    extra = []
    for p in person:
        if p["blacklist"]:
            extra.append({"error_level": blacklist_level,
                          "message": f"段落 {p['section']} 画面出现黑名单人物：{','.join(p['blacklist'])}"
                                     f"（置信度 {p['confidence']}）",
                          "time_range": f"时间轴 {p['section']}"})
    for b in bounds:
        extra.append({"error_level": "block", "message": b["message"],
                      "time_range": f"时间轴 {b['section']} / {b['src']}"})

    issues = narrative["issues"] + extra
    blocks = [i for i in issues if i["error_level"] == "block"]
    warns = [i for i in issues if i["error_level"] == "warn"]

    # 音频告警并入：空档按 audio_skill 分级处理（pause 忽略 / gap warn / eaten block）
    # 注意：吃字/丢台词/低响度告警只对「有台词」的段落（dialogue / V.O.）生效；
    # visual/atmosphere/sync 等非对白段的安静与静默是有意留白，不属于丢台词。
    audio_warns = []
    audio_blocks = []
    for r in audio_rows:
        atype = str(r.get("type", ""))
        is_speech = atype == "dialogue" or any(k in atype for k in ("V.O.", "VO", "独白", "画外"))
        if not is_speech:
            continue
        ds = r.get("drop_summary") or {}
        eaten, gap, pause = ds.get("eaten", 0), ds.get("gap", 0), ds.get("pause", 0)
        if eaten:
            audio_blocks.append({"error_level": "block",
                                 "message": f"{r['section']} 检测到吃字空档（>1.5s）{eaten} 处，"
                                            f"判定丢台词，必须换音频或调整切点",
                                 "time_range": "-"})
        if gap:
            audio_warns.append({"error_level": "warn",
                                "message": f"{r['section']} 疑似吃字空档（0.8~1.5s）{gap} 处，需人工复核",
                                "time_range": "-"})
        if pause and not eaten and not gap:
            audio_warns.append({"error_level": "info",
                                "message": f"{r['section']} {pause} 处能量空档均为自然停顿（<0.8s），自动忽略",
                                "time_range": "-"})
        if r.get("voice_db") is not None and r["voice_db"] < -35:
            audio_warns.append({"error_level": "warn",
                                "message": f"{r['section']} 台词响度偏低（{r['voice_db']}dB）",
                                "time_range": "-"})
    duck_depth = float(bgm_info.get("duck_depth_db", 0.0))
    # BGM 遮盖风险只对「有台词」的段落有意义；非对白段本就靠 BGM 铺底，人声静默时 BGM 响属正常。
    speech_sections = {r["section"] for r in audio_rows
                       if str(r.get("type", "")) == "dialogue"
                       or any(k in str(r.get("type", "")) for k in ("V.O.", "VO", "独白", "画外"))}
    for row in bgm_info.get("per_section", []):
        if row["section"] not in speech_sections:
            continue
        eff = row.get("eff_diff_db")
        if eff is None:
            continue
        if eff < 6:
            audio_warns.append({"error_level": "warn",
                                "message": f"{row['section']} 原声与 BGM 有效差仅 {eff}dB"
                                           f"（静态 {row.get('est_diff_db')}dB + 侧链 {duck_depth}dB），"
                                           f"建议加大 ducking 或提高 BGM 衰减",
                                "time_range": "-"})
    issues += audio_warns + audio_blocks
    blocks = [i for i in issues if i["error_level"] == "block"]
    warns = [i for i in issues if i["error_level"] == "warn"]

    verdict = "FAIL" if blocks else ("WARN" if warns else "PASS")

    scales = Counter(s["shot_scale"] for s in shots)
    short_n = sum(1 for s in shots if s["duration"] < 1.2)
    long_n = sum(1 for s in shots if s["is_long_shot"])
    durations = [c["dur"] for sec in secs for c in sec["clips"]]

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "timeline": str(timeline),
        "project": tl.get("project", ""),
        "video_dir": str(video_dir),
        "gallery": str(gallery),
        "duration_plan": tl.get("duration_plan"),
        "duration_sum": round(sum(durations), 2),
        "verdict": verdict,
        "counts": {"block": len(blocks), "warn": len(warns)},
        "blacklist_buffer_sec": blacklist_buffer,
        "forbidden_effective": forbidden_eff,
        "person": {"sections": person, "windows": person_detail},
        "shots": {"count": len(shots), "scales": dict(scales), "short_shots": short_n,
                  "long_shots": long_n,
                  "motion_min": min((s["motion_score"] for s in shots), default=None),
                  "motion_max": max((s["motion_score"] for s in shots), default=None),
                  "list": shots},
        "narrative": narrative,
        "audio": {"sections": audio_rows, "bgm": bgm_info},
        "bounds": bounds,
        "issues": issues,
    }
    (outdir / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (outdir / "quality_report.md").write_text(render_md(report), encoding="utf-8")
    return report


def _cell(v) -> str:
    return "-" if v is None else str(v)


def render_md(r: dict) -> str:
    L = [f"# 成片质量综合巡检报告 — {r.get('project') or Path(r['timeline']).stem}", "",
         f"- 生成时间：{r['generated_at']}",
         f"- 时间轴：`{r['timeline']}`（计划 {r['duration_plan']}s / 实排 {r['duration_sum']}s）",
         f"- 素材目录：`{r['video_dir']}`",
         f"- 头像库：`{r['gallery']}`",
         f"- **总结论：{r['verdict']}**（block {r['counts']['block']} / warn {r['counts']['warn']}）",
         "- 说明：本报告只做分析，不渲染视频；音频指标为素材源轨实测，非成片混音实测。", "",
         "## 检查项总览", "",
         "| 检查项 | 结论 | 关键发现 |", "|---|---|---|"]

    black_hits = [p for p in r["person"]["sections"] if p["blacklist"]]
    target_hits = [p for p in r["person"]["sections"] if p["target"]]
    L.append(f"| 人物黑名单命中 | {'FAIL' if black_hits else 'PASS'} | "
             + ("命中：" + "；".join(f"{p['section']}→{','.join(p['blacklist'])}" for p in black_hits)
                if black_hits else "未检出黑名单人物") + " |")
    L.append(f"| 主角出镜 | INFO | "
             + ("；".join(f"{p['section']}→{','.join(p['target'])}" for p in target_hits) or "未检出目标主角") + " |")
    sh = r["shots"]
    L.append(f"| 镜头节奏 | "
             f"{'WARN' if sh['short_shots'] > 0.4 * max(1, sh['count']) else 'PASS'} | "
             f"{sh['count']} 镜 / 景别 {sh['scales']} / 碎镜 {sh['short_shots']} / 长镜 {sh['long_shots']} |")
    nar = r["narrative"]
    L.append(f"| 叙事顺序 & J-cut | {nar['verdict']} | block {nar['counts']['block']} / warn {nar['counts']['warn']} |")
    L.append(f"| 禁止支线命中 | {'FAIL' if any(i['message'].startswith('命中禁止支线') for i in r['issues']) else 'PASS'} | "
             f"{sum(1 for i in r['issues'] if i['message'].startswith('命中禁止支线'))} 处"
             f"（含 ±{r.get('blacklist_buffer_sec', 0)}s 避让缓冲） |")
    fb_eff = [f for f in r.get("forbidden_effective", []) if f.get("start", -1) >= 0]
    if fb_eff:
        L.append(f"| 黑名单避让窗口 | INFO | "
                 + "；".join(f"{f.get('name')} {f.get('src')} {f.get('orig_start')}–{f.get('orig_end')}"
                             f"→有效 {f.get('start')}–{f.get('end')}" for f in fb_eff) + " |")
    ds_all = [a.get("drop_summary") or {} for a in r["audio"]["sections"]]
    n_pause = sum(d.get("pause", 0) for d in ds_all)
    n_gap = sum(d.get("gap", 0) for d in ds_all)
    n_eaten = sum(d.get("eaten", 0) for d in ds_all)
    voice_low = [a["section"] for a in r["audio"]["sections"]
                 if a["voice_db"] is not None and a["voice_db"] < -35]
    L.append(f"| 音频指标 | {'FAIL' if n_eaten else ('WARN' if (n_gap or voice_low) else 'PASS')} | "
             f"自然停顿 {n_pause} 处（已忽略）/ 疑似吃词 {n_gap} 处 / 吃字 {n_eaten} 处 / "
             f"低响度段 {voice_low or '无'} |")
    L.append(f"| 素材边界 | {'FAIL' if r['bounds'] else 'PASS'} | {len(r['bounds'])} 处越界 |")
    L += ["", "## 1. 人物出镜核查", "",
          "| 段落 | 目标主角 | 黑名单 | 人脸数 | 最高相似度 | 判定 |", "|---|---|---|---|---|---|"]
    if r["person"]["sections"]:
        for p in r["person"]["sections"]:
            L.append(f"| {p['section']} | {','.join(p['target']) or '-'} | "
                     f"{','.join(p['blacklist']) or '-'} | {p['face_count']} | {p['confidence']} | {p['verdict']} |")
    else:
        L.append("| - | - | - | - | - | 已跳过（--skip-person） |")
    L += ["", "> 局限：背光、强侧脸、遮挡、远距离小人脸会漏检；黑名单命中仅代表画面相似，需人工复核。", ""]

    L += ["## 2. 镜头语义与节奏", "",
          f"- 镜头数 {sh['count']}；景别分布 {sh['scales']}；碎镜 {sh['short_shots']}；长镜 {sh['long_shots']}",
          f"- motion_score 范围 {_cell(sh['motion_min'])} ~ {_cell(sh['motion_max'])}", "",
          "| # | 来源 | 起 | 止 | 时长 | 景别 | 人脸占比 | motion | 长镜 |", "|---|---|---|---|---|---|---|---|---|"]
    for i, s in enumerate(sh["list"], 1):
        L.append(f"| {i} | {Path(s['source']).name} | {s['start_time']} | {s['end_time']} | "
                 f"{s['duration']} | {s['shot_scale']} | {s['face_area_ratio']} | "
                 f"{s['motion_score']} | {int(s['is_long_shot'])} |")
    L += ["", "## 3. 叙事 / J-cut / 禁支线", ""]
    L += render_narrative_md(nar).splitlines()[4:]
    L += ["", "## 4. 音频指标（素材源轨实测）", "",
          "| 段落 | 类型 | 台词响度dB | 空档 | 备注 |", "|---|---|---|---|---|"]
    for a in r["audio"]["sections"]:
        L.append(f"| {a['section']} | {a['type']} | {_cell(a['voice_db'])} | "
                 f"{len(a['speech_drops'])} | {a.get('skip') or '；'.join(a['flags']) or '正常'} |")
    b = r["audio"]["bgm"]
    L += ["", f"- BGM：`{Path(b.get('file', '')).name}` 时长 {b.get('duration', '-')}s / "
              f"原始均值 {_cell(b.get('bgm_mean_db'))}dB / 计划增益 {b.get('planned_gain_db')}dB / "
              f"计划入场 {b.get('planned_entry_sec')}s / 侧链压低档位 {b.get('duck_depth_db')}dB"]
    if b.get("per_section"):
        L += ["", "| 段落 | 原声dB | BGM估算dB | 静态差dB | 有效差dB(含侧链) |", "|---|---|---|---|---|"]
        for row in b["per_section"]:
            L.append(f"| {row['section']} | {row['voice_db']} | {_cell(row['bgm_est_db'])} | "
                     f"{_cell(row['est_diff_db'])} | {_cell(row.get('eff_diff_db'))} |")
        L += ["", f"> {b['note']}"]
    L += ["", "## 5. 问题清单（按级别）", ""]
    if r["issues"]:
        for i in r["issues"]:
            L.append(f"- **[{i['error_level']}]** {i['message']}（{i['time_range']}）")
    else:
        L.append("- 无问题")
    L += ["", "## 6. 处理建议", ""]
    if any(i["error_level"] == "block" for i in r["issues"]):
        L.append("- 存在 block 级问题：必须重剪或换素材，不能直接进入渲染。")
    if any(i["error_level"] == "warn" for i in r["issues"]):
        L.append("- 存在 warn 级问题：确认可接受后可人工放行（例如文艺片的有意 J-cut）。")
    if not r["issues"]:
        L.append("- 全部通过，可进入下一步渲染流程。")
    L += ["", "---", "> 本报告由 quality_check_all.py 生成，未生成任何视频文件。"]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="成片质量综合巡检（只分析，不渲染）")
    ap.add_argument("--timeline", required=True)
    ap.add_argument("--video-dir", default=r"D:\00_skiill_ku\03_video\assets\elephant\raw")
    ap.add_argument("--gallery", default=r"D:\00_skiill_ku\03_video\assets\elephant\faces")
    ap.add_argument("--forbidden", default="", help="禁止支线 JSON 路径")
    ap.add_argument("--emotion-script", default=",".join(DEFAULT_EMOTIONS))
    ap.add_argument("--allow-jcut", dest="allow_jcut", action="store_true", default=True)
    ap.add_argument("--no-allow-jcut", dest="allow_jcut", action="store_false")
    ap.add_argument("--blacklist-level", choices=["block", "warn"], default="block")
    ap.add_argument("--blacklist-buffer", type=float, default=5.0,
                    help="敏感人物/禁支线窗口前后避让缓冲秒数（默认 5）")
    ap.add_argument("--bgm", default="")
    ap.add_argument("--outdir", default="demo_out")
    ap.add_argument("--skip-person", action="store_true")
    ap.add_argument("--skip-shot", action="store_true")
    a = ap.parse_args()

    forbidden = (json.loads(Path(a.forbidden).read_text(encoding="utf-8"))
                 if a.forbidden else None)
    script = [x.strip() for x in a.emotion_script.split(",") if x.strip()]
    rep = run(Path(a.timeline), Path(a.video_dir), Path(a.gallery), Path(a.outdir),
              forbidden, script, a.allow_jcut, Path(a.bgm) if a.bgm else None,
              a.blacklist_level, skip_person=a.skip_person, skip_shot=a.skip_shot,
              blacklist_buffer=a.blacklist_buffer)
    print(f"{rep['verdict']} block={rep['counts']['block']} warn={rep['counts']['warn']}"
          f" -> {Path(a.outdir) / 'quality_report.md'}")
    return 0 if rep["verdict"] == "PASS" else (1 if rep["verdict"] == "WARN" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
