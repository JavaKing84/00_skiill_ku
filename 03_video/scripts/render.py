#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render.py — 03_video 最小渲染脚本（跨客户端可复现）。

能力边界（只做基础项，不重复 aitoearn 的复杂混剪）：
  多段视频拼接 → 统一画幅（9:16 / 16:9 / 1:1）→ 可选字幕 → 可选**已登记授权**的 BGM 混音
  → loudnorm 响度归一 → H.264/AAC 导出 → 可选自动 QC。

安全约束：
  - BGM 必须登记在 assets/BGM_LICENSES.json，未登记直接拒绝（BLOCKED），不使用版权不明音乐。
  - 不做任何真实发布；发布一律走 publish_preview.py（dry-run）。
  - 缺字体/编码器/BGM 时明确报错，不静默降级。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_shared"))
from skillkit.media import ffprobe, summarize  # noqa: E402

ASPECTS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080),
           "4:5": (1080, 1350)}
BGM_REGISTRY = ROOT / "assets" / "BGM_LICENSES.json"
DEFAULT_FONT = Path(r"C:\Windows\Fonts\msyhbd.ttc")


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=1800)


def check_tools() -> dict:
    """检查 ffmpeg/ffprobe/编码器/滤镜/字体，缺失即报告（不静默降级）。"""
    problems = []
    ff = run(["ffmpeg", "-version"])
    if ff.returncode != 0:
        problems.append("ffmpeg 不可用")
    enc = run(["ffmpeg", "-hide_banner", "-encoders"])
    enc_txt = enc.stdout + enc.stderr
    for need in ("libx264", "aac"):
        if need not in enc_txt:
            problems.append(f"缺少编码器 {need}")
    filt = run(["ffmpeg", "-hide_banner", "-filters"])
    filt_txt = filt.stdout + filt.stderr
    for need in ("drawtext", "amix", "concat", "loudnorm", "anullsrc"):
        if need not in filt_txt:
            problems.append(f"缺少滤镜 {need}")
    if not DEFAULT_FONT.exists():
        problems.append(f"缺少中文字体 {DEFAULT_FONT}")
    return {"ok": not problems, "problems": problems,
            "ffmpeg": ff.stdout.splitlines()[0] if ff.stdout else "unknown"}


def bgm_allowed(bgm_path: Path) -> tuple[bool, str]:
    """BGM 必须在授权登记表中；未登记一律拒绝。"""
    if not BGM_REGISTRY.exists():
        return False, f"授权登记表不存在：{BGM_REGISTRY}"
    try:
        data = json.loads(BGM_REGISTRY.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"授权登记表解析失败：{exc}"
    for item in data.get("bgm", []):
        p = Path(item.get("path", ""))
        if p.name.lower() == bgm_path.name.lower() and item.get("license"):
            return True, f"{item.get('name')} / {item.get('license')} / {item.get('source')}"
    return False, f"BGM 未登记授权：{bgm_path.name}"


def has_audio(path: Path) -> bool:
    try:
        probe = ffprobe(path)
    except Exception:
        return False
    return any(s.get("codec_type") == "audio" for s in probe.get("streams", []))


def _filter_path(path: Path | str) -> str:
    """把 Windows 路径转成 ffmpeg filter 语法安全形式：正斜杠 + 转义冒号（如 C\\:/Windows/...）。"""
    return str(path).replace("\\", "/").replace(":", "\\:")


def build_render(inputs: list[Path], out: Path, aspect: str, subtitle: str | None,
                 bgm: Path | None, bgm_gain_db: float, fps: int) -> tuple[list[str], list[str]]:
    """返回 (ffmpeg 输入参数, filter_complex 片段)。"""
    args: list[str] = []
    fc: list[str] = []
    videos, audios = [], []
    for i, src in enumerate(inputs):
        args += ["-i", str(src)]
        videos.append(f"[{i}:v]")
        if has_audio(src):
            audios.append(f"[{i}:a]")
    w, h = ASPECTS.get(aspect, ASPECTS["16:9"])
    for i in range(len(inputs)):
        fc.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                  f"crop={w}:{h},setsar=1,fps={fps}[v{i}]")
    vconcat = "".join(f"[v{i}]" for i in range(len(inputs)))
    fc.append(f"{vconcat}concat=n={len(inputs)}:v=1:a=0[vcat]")
    if len(audios) == len(inputs) and audios:
        for i in range(len(inputs)):
            fc.append(f"[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]")
        acat = "".join(f"[a{i}]" for i in range(len(inputs)))
        fc.append(f"{acat}concat=n={len(inputs)}:v=0:a=1[aout]")
        audio_label = "[aout]"
    else:
        fc.append("anullsrc=r=48000:cl=stereo,atrim=duration=0.1[aout0]")
        fc.append("[aout0]apad[aout]")
        audio_label = "[aout]"

    if bgm:
        args += ["-stream_loop", "-1", "-i", str(bgm)]
        bi = len(inputs)
        fc.append(f"[{bi}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                  f"volume={bgm_gain_db}dB[bgm]")
        fc.append(f"{audio_label}[bgm]amix=inputs=2:duration=first:dropout_transition=0[amixed]")
        audio_label = "[amixed]"
    fc.append(f"{audio_label}loudnorm=I=-16:TP=-1.5:LRA=11[afinal]")
    audio_label = "[afinal]"

    vlabel = "[vcat]"
    if subtitle:
        text_file = Path(tempfile.gettempdir()) / "video_pipeline_subtitle.txt"
        text_file.write_text(subtitle, encoding="utf-8")
        # 用单引号包裹路径值，避免冒号被当作选项分隔符
        font_path = f"'{_filter_path(DEFAULT_FONT)}'"
        text_path = f"'{_filter_path(text_file)}'"
        fc.append(f"{vlabel}drawtext=fontfile={font_path}:textfile={text_path}:"
                  f"fontcolor=white:fontsize=36:borderw=4:bordercolor=black@0.8:"
                  f"x=(w-text_w)/2:y=h-text_h-60[vsub]")
        vlabel = "[vsub]"
    return args, fc, vlabel, audio_label


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", required=True, help="输入视频（按顺序拼接）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--aspect", default="16:9", choices=list(ASPECTS))
    ap.add_argument("--subtitle", default="", help="字幕文本（单条，底部）")
    ap.add_argument("--bgm", default="", help="BGM 路径（必须在授权登记表内）")
    ap.add_argument("--bgm-gain-db", type=float, default=-18.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--qc", action="store_true", help="渲染后自动执行 video_qc.py")
    args = ap.parse_args()

    tools = check_tools()
    if not tools["ok"]:
        print("BLOCKED: 运行环境不满足渲染要求：" + "; ".join(tools["problems"]))
        return 2

    inputs = [Path(p) for p in args.inputs]
    missing = [str(p) for p in inputs if not p.exists()]
    if missing:
        print(f"FAIL: 输入不存在 {missing}")
        return 2

    bgm = Path(args.bgm) if args.bgm else None
    bgm_note = ""
    if bgm:
        ok, note = bgm_allowed(bgm)
        if not ok:
            print(f"BLOCKED: {note}")
            print("提示：先在 03_video/assets/BGM_LICENSES.json 登记授权信息。")
            return 2
        if not bgm.exists():
            print(f"BLOCKED: BGM 文件不存在 {bgm}")
            return 2
        bgm_note = note

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    in_args, fc, vlabel, alabel = build_render(inputs, out, args.aspect,
                                               args.subtitle or None, bgm, args.bgm_gain_db, args.fps)
    cmd = ["ffmpeg", "-y", *in_args,
           "-filter_complex", ";".join(fc),
           "-map", vlabel, "-map", alabel,
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-ar", "48000", "-movflags", "+faststart", str(out)]
    p = run(cmd)
    if p.returncode != 0 or not out.exists():
        print("FAIL: ffmpeg 渲染失败")
        print((p.stderr or "")[-1500:])
        return 2

    meta = summarize(ffprobe(out))
    result = {
        "inputs": [str(i) for i in inputs],
        "output": str(out),
        "bytes": out.stat().st_size,
        "aspect": args.aspect,
        "subtitle": bool(args.subtitle),
        "bgm": bgm_note or None,
        "probe": meta,
    }
    qc_out = ""
    if args.qc:
        qc_dir = out.parent / (out.stem + "_qc")
        q = subprocess.run([sys.executable, str(ROOT / "scripts" / "video_qc.py"),
                            "--video", str(out), "--out", str(qc_dir)],
                           capture_output=True, text=True, timeout=600)
        qc_out = (q.stdout or "").strip()
        result["qc"] = qc_out
        result["qc_exit"] = q.returncode
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.qc:
        print(f"QC: {qc_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
