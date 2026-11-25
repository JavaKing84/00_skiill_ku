#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""montage_edit.py — 基于 EDL 的确定性混剪渲染器（可复现，不做黑箱）。

能力：
  - 按 EDL 逐段裁剪源素材（A/V 同源，保证声画同步）
  - 统一画幅/帧率/像素格式（不拉伸；等比放大后居中裁切）
  - 统一电影感调色（降饱和/轻压暗部/冷调/暗角）
  - 无音轨的补充空镜自动补静音，保证拼接一致
  - BGM 侧链闪避（对白出现时自动压低），loudnorm 归一，片尾淡出
  - 输出 ffprobe 摘要 JSON，供视频 QC 与报告引用

用法：
  python montage_edit.py --edl <edl.json> --out <final.mp4> [--work <中间目录>]
EDL 结构见 03_video/examples/edl_example.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_shared"))
from skillkit.media import ffprobe, summarize  # noqa: E402
from audio_skill import audio_ducking, audio_diagnose  # noqa: E402

GRADES = {
    "none": "",
    "dark_cool": ("eq=saturation=0.78:contrast=1.06:brightness=-0.03,"
                  "colorbalance=bs=0.06:bm=0.03:bh=-0.02,vignette=PI/5"),
    "warm_film": "eq=saturation=0.9:contrast=1.04,colorbalance=rs=0.03:bs=-0.03",
}

# 动态侧链压缩默认参数：以人声轨为触发，台词期间 BGM 自动压低 ≥ duck_target_db。
# ratio=9 + threshold=0.03 对 -20dBFS 上下的人声约产生 8~12dB 压低；bgm_gain_db 为
# 静态打底衰减（保证句间空隙 BGM 也不抢戏）。均可被 EDL json 的 bgm.ducking 覆盖。
DUCK_DEFAULTS = {"threshold": 0.03, "ratio": 9.0, "attack": 6.0, "release": 380.0,
                 "makeup": 1.0, "level_sc": 1.0, "duck_target_db": 6.0}


def run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def has_audio(path: str) -> bool:
    try:
        return any(s.get("codec_type") == "audio" for s in ffprobe(path).get("streams", []))
    except Exception:
        return False


def src_duration(path: str) -> float:
    try:
        fmt = ffprobe(path).get("format", {})
        return float(fmt.get("duration") or 0.0)
    except Exception:
        return 0.0


def validate_segments(edl: dict) -> list[str]:
    """时长守卫第一道：每个段的 start+dur 不得超出源素材实际时长。

    防两类怪片根源：素材不足时 ffmpeg 会产出更短的段，拼接节奏错乱；
    start 为负则直接截断到 0，画面跳变。
    """
    errs = []
    cache: dict[str, float] = {}
    for i, seg in enumerate(edl["segments"], 1):
        src = seg["src"]
        start = float(seg.get("start", 0))
        dur = float(seg["dur"])
        if dur <= 0:
            errs.append(f"段 {i}（{seg.get('label', 'S' + str(i))}）：dur={dur} 必须为正数")
            continue
        if start < 0:
            errs.append(f"段 {i}（{seg.get('label', 'S' + str(i))}）：start={start} 不能为负")
            continue
        if src not in cache:
            cache[src] = src_duration(src)
        avail = cache[src]
        if avail <= 0:
            errs.append(f"段 {i}：无法读取源时长 {src}（文件损坏或不是视频？）")
            continue
        if start + dur > avail + 0.05:
            errs.append(
                f"段 {i}（{seg.get('label', 'S' + str(i))}）：start={start:.2f}+dur={dur:.2f}"
                f" 超出源时长 {avail:.2f}s（{Path(src).name}）。"
                f"该源最多可用 {max(0.0, avail - start):.2f}s——请缩短 dur 或换素材，"
                f"禁止用补帧/慢放硬凑时长")
    return errs


def build_video_filter(start: float, dur: float, w: int, h: int, fps: int,
                       grade: str, fit: str, extra: str = "", pre_crop: str = "") -> tuple[str, str]:
    """返回 (模式, 滤镜串)。模式 vf=线性链；fc=需要 filter_complex。

    fit=cover    ：等比放大后居中裁切填满。**宽银幕/16:9 素材转 9:16 会放大 1.7~2 倍、
                   横向只剩三成，人物会被裁出画面**——只有在素材本身接近目标比例时才用。
    fit=blur_pad ：完整保留原构图（等比缩放放进画幅），空余区域用同画面模糊放大填充。
                   转竖屏的默认选择，不裁人物、不留纯黑边。
    """
    head = f"trim=start={start}:duration={dur},setpts=PTS-STARTPTS"
    if pre_crop:
        # 段级 pre_crop：在 blur_pad 缩放之前裁掉源帧的水印/烧录字幕条，
        # bg/fg 两条链都走 [0:v]{head}，故对两者同时生效（crop 先于 blur_pad）。
        head += "," + pre_crop
    # blur_pad 模式下背景是"环境色"而非主体，压太暗等于黑边；同时去掉暗角，
    # 否则竖屏上下两端叠两层压暗，观感就是"半个镜头都是黑的"。
    grade_eff = grade.replace(",vignette=PI/5", "")
    tail = (f",fps={fps},setsar=1" + (("," + grade_eff) if grade_eff else "")
            + (("," + extra) if extra else ""))
    if fit == "cover":
        return "vf", (f"{head},scale={w}:{h}:force_original_aspect_ratio=increase,"
                      f"crop={w}:{h}" + tail)
    bg = (f"[0:v]{head},scale={w}:{h}:force_original_aspect_ratio=increase,"
          f"crop={w}:{h},gblur=sigma=22,eq=brightness=-0.04:saturation=0.55[bg]")
    fg = f"[0:v]{head},scale={w}:{h}:force_original_aspect_ratio=decrease[fg]"
    return "fc", f"{bg};{fg};[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=1{tail}[v]"


def render_segment(src: str, start: float, dur: float, out: Path, w: int, h: int, fps: int,
                   grade: str, fit: str = "blur_pad", extra: str = "", pre_crop: str = "") -> dict:
    mode, vchain = build_video_filter(start, dur, w, h, fps, grade, fit, extra, pre_crop)
    af = f"atrim=start={start}:duration={dur},asetpts=PTS-STARTPTS,aresample=48000"
    af = f"{af},aformat=sample_fmts=fltp:channel_layouts=stereo"
    base = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src]
    enc = ["-t", str(dur), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(out)]
    if has_audio(src):
        if mode == "vf":
            cmd = base + ["-vf", vchain, "-af", af] + enc
        else:
            cmd = base + ["-filter_complex", f"{vchain};[0:a]{af}[a]",
                          "-map", "[v]", "-map", "[a]"] + enc
    else:
        cmd = base + ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        if mode == "vf":
            cmd += ["-vf", vchain]
        else:
            cmd += ["-filter_complex", f"{vchain};[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo[a]",
                    "-map", "[v]", "-map", "[a]"]
        cmd += ["-t", str(dur), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2",
                "-shortest", str(out)]
    p = run(cmd)
    if p.returncode != 0 or not out.exists():
        raise RuntimeError(f"segment failed: {src} @{start}+{dur}: {p.stderr[:400]}")
    # 时长守卫第二道：渲染出的段必须真的等于 dur（±0.35s），否则立即报错，
    # 不允许"段悄悄变短→成片节奏错乱"静默通过。
    actual = src_duration(str(out))
    dev = abs(actual - dur)
    if dev > 0.35:
        raise RuntimeError(
            f"段渲染时长异常：计划 {dur:.2f}s，实得 {actual:.2f}s（偏差 {dev:.2f}s）。"
            f"多半是源素材不足或被解码器提前截断：{src} @{start}+{dur}")
    return {"src": src, "start": start, "dur": dur, "file": str(out),
            "actual_dur": round(actual, 2)}


def mix_final(silent: Path, bgm_path: str, total: float, gain: float, fade: float,
              duck: dict, out: Path) -> None:
    """按给定侧链参数做一次最终混音（c:v copy，仅重编码音频）。"""
    # 侧链：以对白轨 [0:a] 为触发压低 BGM；静态打底衰减 gain 在前面 volume 完成
    duck_chain = audio_ducking(voice_label="0:a", bgm_label="bgm_pre",
                               threshold=duck["threshold"], ratio=duck["ratio"],
                               attack=duck["attack"], release=duck["release"],
                               makeup=duck["makeup"], sc_level=duck["level_sc"],
                               bgm_gain_db=0.0, out_label="bgmduck")
    fc = (
        f"[1:a]volume={gain}dB,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"atrim=0:{total},asetpts=PTS-STARTPTS[bgm_pre];"
        f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[dial];"
        f"{duck_chain};"
        f"[dial][bgmduck]amix=inputs=2:duration=first:dropout_transition=0:weights=1 1[mix];"
        f"[mix]loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=out:st={max(0.0, total - fade)}:d={fade}[a]"
    )
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(silent),
           "-stream_loop", "-1", "-i", str(bgm_path),
           "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
           "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2",
           "-movflags", "+faststart", "-t", str(total), str(out)]
    p = run(cmd)
    if p.returncode != 0 or not out.exists():
        raise RuntimeError(f"final mix failed: {p.stderr[:500]}")


def build_bgm_ref(silent: Path, bgm_path: str, total: float, gain: float,
                  duck: dict, out_wav: Path) -> None:
    """重建一条「仅用于测量」的被侧链压侧后的 BGM 参考轨（不参与成片）。

    滤镜链与 mix_final 完全一致（BGM 静态 gain → sidechaincompress，触发源为 silent 的对白轨），
    但只输出 [bgmduck] 分支、不做 amix/loudnorm/fade。因此测得的 ducking_db 是真实的侧链压侧深度，
    voice_bgm_diff 为「成片混音 − 该参考轨」的近似（成片后级 loudnorm 为全局归一，影响可忽略并已注明）。
    """
    duck_chain = audio_ducking(
        voice_label="0:a", bgm_label="bgm_pre",
        threshold=duck["threshold"], ratio=duck["ratio"],
        attack=duck["attack"], release=duck["release"],
        makeup=duck["makeup"], sc_level=duck["level_sc"],
        bgm_gain_db=0.0, out_label="bgmduck")
    fc = (
        f"[1:a]volume={gain}dB,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"atrim=0:{total},asetpts=PTS-STARTPTS[bgm_pre];"
        f"{duck_chain}"
    )
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(silent), "-stream_loop", "-1", "-i", str(bgm_path),
           "-filter_complex", fc, "-map", "[bgmduck]", "-t", str(total),
           "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(out_wav)]
    p = run(cmd)
    if p.returncode != 0 or not out_wav.exists():
        raise RuntimeError(f"bgm ref build failed: {p.stderr[:400]}")


def measure_duck(final: Path, target_db: float,
                 bgm_ref_path: str | Path | None = None) -> dict:
    """混音后实测台词段 BGM 压低量（只抽音轨分析，不碰视频）。

    bgm_ref_path：独立的（被侧链压侧后的）BGM 参考轨。传 None / 文件不存在时，
    诚实返回 ducking_db=None，并附明确 flag——禁止把同一混音同时当 voice 和 bgm 传入，
    那样 voice_bgm_diff 恒为 0、ducking_db 符号反转，是无效伪影。
    """
    wav = final.with_suffix(".duckchk.wav")
    p = run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(final),
             "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    if p.returncode != 0 or not wav.exists():
        return {"measured_ducking_db": None, "guard": "SKIP", "flags": ["音频抽取失败，无法实测压侧量"]}
    flags = []
    if bgm_ref_path is not None and Path(bgm_ref_path).exists():
        rep = audio_diagnose(wav, str(bgm_ref_path), None, is_mix=True, min_duck_db=target_db)
    else:
        rep = audio_diagnose(wav, None, None, is_mix=True, min_duck_db=target_db)
        flags.append("未提供独立 BGM 参考轨（bgm_ref_path 缺失），ducking_db/voice_bgm_diff 无法实测；"
                     "已禁用混音自比伪影，结果为 None")
    wav.unlink(missing_ok=True)
    measured = rep.get("ducking_db")
    if measured is None:
        guard = "WARN"
    elif measured <= -target_db:
        guard = "PASS"
    else:
        guard = "WARN"
    return {"measured_ducking_db": measured, "voice_bgm_diff": rep.get("voice_bgm_diff"),
            "target_db": target_db, "guard": guard,
            "flags": flags + rep.get("flags", [])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--edl", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--work", default="")
    args = ap.parse_args()

    edl = json.loads(Path(args.edl).read_text(encoding="utf-8"))
    w = int(edl.get("width", 1080)); h = int(edl.get("height", 1080))
    fps = int(edl.get("fps", 30))
    grade = GRADES.get(edl.get("grade", "none"), "")
    fit = edl.get("fit", "blur_pad")
    work = Path(args.work or (Path(args.out).parent / "parts"))
    work.mkdir(parents=True, exist_ok=True)

    # 时长守卫第一道：渲染前先验证所有段都可从源素材完整取得
    seg_errs = validate_segments(edl)
    if seg_errs:
        print("BLOCKED: EDL 时长守卫未通过（不渲染，先修 EDL）：")
        for e in seg_errs:
            print(f"  - {e}")
        return 2

    parts, total = [], 0.0
    for i, seg in enumerate(edl["segments"], 1):
        dur = float(seg["dur"])
        total += dur
        out = work / f"part_{i:02d}.mp4"
        meta = render_segment(seg["src"], float(seg.get("start", 0)), dur, out, w, h, fps,
                              grade, fit, seg.get("extra_grade", ""), seg.get("pre_crop", ""))
        meta["label"] = seg.get("label", f"S{i}")
        parts.append(meta)
        print(f"  {meta['label']:>4} {dur:6.2f}s (实得 {meta['actual_dur']:.2f}s) -> {out.name}")

    concat_list = work / "concat.txt"
    concat_list.write_text("".join(f"file '{p['file'].replace(chr(92), '/')}'\n" for p in parts),
                           encoding="utf-8")
    silent = work / "silent.mp4"
    p = run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", str(concat_list),
             "-c", "copy", str(silent)])
    if p.returncode != 0:
        raise RuntimeError(f"concat failed: {p.stderr[:400]}")

    bgm = edl.get("bgm") or {}
    final = Path(args.out)
    final.parent.mkdir(parents=True, exist_ok=True)
    duck_result = None
    if bgm.get("path") and Path(bgm["path"]).exists():
        gain = float(bgm.get("gain_db", -14))
        fade = float(edl.get("fade_out", 3.0))
        # 动态侧链：参数可被 EDL bgm.ducking 覆盖；混音后实测压低量，
        # 未达 duck_target_db（默认 6dB）自动加强（ratio+3 / threshold×0.6 / 静态-3dB）重混
        duck = dict(DUCK_DEFAULTS)
        duck.update(bgm.get("ducking") or {})
        target_db = float(duck.pop("duck_target_db", 6.0))
        attempts = []
        for attempt in (1, 2):
            mix_final(silent, bgm["path"], total, gain, fade, duck, final)
            bgm_ref = work / f"duck_ref_{attempt}.wav"
            build_bgm_ref(silent, bgm["path"], total, gain, duck, bgm_ref)
            chk = measure_duck(final, target_db, bgm_ref)
            bgm_ref.unlink(missing_ok=True)
            attempts.append({"attempt": attempt, "gain_db": gain, "params": dict(duck), **chk})
            print(f"  duck check #{attempt}: ducking_db={chk['measured_ducking_db']} "
                  f"(target <= -{target_db}dB) guard={chk['guard']}")
            if chk["guard"] == "PASS":
                break
            duck["ratio"] = round(float(duck["ratio"]) + 3, 1)
            duck["threshold"] = round(float(duck["threshold"]) * 0.6, 4)
            gain = round(gain - 3, 1)
        duck_result = {"duck_target_db": target_db, "final_gain_db": gain,
                       "final_params": dict(duck), "attempts": attempts,
                       "guard": attempts[-1]["guard"]}
        if duck_result["guard"] != "PASS":
            print(f"WARN 侧链压低未达 {target_db}dB 目标"
                  f"（实测 {attempts[-1].get('measured_ducking_db')}dB），需人工复核")
    else:
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(silent),
               "-c", "copy", "-movflags", "+faststart", str(final)]
        p = run(cmd)
        if p.returncode != 0 or not final.exists():
            raise RuntimeError(f"final mix failed: {p.stderr[:500]}")

    probe = ffprobe(str(final))
    summary = summarize(probe)
    actual_dur = summary.get("duration_seconds") or 0.0
    deviation = round(abs(actual_dur - total), 2)
    # 时长守卫第三道：成片整体时长必须等于计划总时长（±1s）
    guard = "PASS" if deviation <= 1.0 else "FAIL"
    if bgm.get("path"):
        audio_source = "bgm"
    elif any(has_audio(s["src"]) for s in edl.get("segments", [])):
        audio_source = "source"
    else:
        audio_source = "silence"
    if audio_source == "silence":
        print("WARN 所有素材无音轨且未配置 BGM：成片为静音，发布前需补 BGM 或原声")
    result = {
        "output": str(final), "bytes": final.stat().st_size,
        "planned_duration": round(total, 2), "actual_duration": actual_dur,
        "duration_deviation": deviation, "duration_guard": guard,
        "audio_source": audio_source,
        "probe": summary,
        "segments": parts, "grade": edl.get("grade"),
        "bgm": {"path": bgm.get("path"), "gain_db": bgm.get("gain_db"),
                "ducking": "sidechaincompress(dynamic)" if duck_result else None,
                "duck_check": duck_result,
                "verified_identity": bgm.get("verified_identity", False)},
    }
    print(json.dumps({"output": result["output"], "bytes": result["bytes"],
                      "planned_duration": round(total, 2), "duration": actual_dur,
                      "duration_guard": guard, "audio_source": audio_source,
                      "video": summary.get("video"),
                      "audio": summary.get("audio")}, ensure_ascii=False, indent=2))
    rp = final.with_suffix(".json")
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {rp}")
    if guard == "FAIL":
        print(f"DURATION_GUARD_FAIL: 成片 {actual_dur:.2f}s vs 计划 {total:.2f}s，"
              f"偏差 {deviation:.2f}s > 1.0s。请检查 EDL 与源素材，禁止交付。")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
