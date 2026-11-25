"""ffprobe / ffmpeg 封装：元信息、镜头切换、黑屏/静音检测。纯 subprocess + 标准库。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class ProbeError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def ffprobe(path: str | Path) -> dict[str, Any]:
    """返回 ffprobe JSON（format + streams）。失败抛 ProbeError。"""
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    p = _run(cmd)
    if p.returncode != 0:
        raise ProbeError(p.stderr.strip())
    return json.loads(p.stdout)


def summarize(probe: dict[str, Any]) -> dict[str, Any]:
    """从 ffprobe JSON 提取 QC 关心的扁平字段。"""
    out: dict[str, Any] = {"duration_seconds": None, "video": None, "audio": None, "container": None}
    fmt = probe.get("format", {})
    out["container"] = fmt.get("format_name")
    try:
        out["duration_seconds"] = round(float(fmt.get("duration", 0)), 3)
    except (TypeError, ValueError):
        pass
    for s in probe.get("streams", []):
        if s.get("codec_type") == "video" and out["video"] is None:
            out["video"] = {
                "codec": s.get("codec_name"),
                "width": s.get("width"),
                "height": s.get("height"),
                "fps": _parse_fps(s.get("avg_frame_rate")),
                "pix_fmt": s.get("pix_fmt"),
            }
        elif s.get("codec_type") == "audio" and out["audio"] is None:
            out["audio"] = {
                "codec": s.get("codec_name"),
                "sample_rate": s.get("sample_rate"),
                "channels": s.get("channels"),
            }
    return out


def _parse_fps(rate: str | None) -> float | None:
    if not rate or "/" not in rate:
        return None
    num, den = rate.split("/")
    try:
        den_f = float(den)
        return round(float(num) / den_f, 3) if den_f else None
    except (TypeError, ValueError):
        return None


def scene_cuts(path: str | Path, threshold: float = 0.35) -> list[float]:
    """用 ffmpeg select='gt(scene,T)' 输出镜头切换时间点（秒）。"""
    cmd = [
        "ffmpeg", "-i", str(path),
        "-filter:v", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]
    p = _run(cmd, timeout=600)
    cuts = []
    for line in p.stderr.splitlines():
        if "pts_time:" in line:
            try:
                token = [t for t in line.split() if t.startswith("pts_time:")][0]
                cuts.append(round(float(token.split(":")[1]), 3))
            except (IndexError, ValueError):
                continue
    return cuts


def blackdetect(path: str | Path, min_duration: float = 0.5) -> list[dict[str, float]]:
    """黑屏段检测，返回 [{start,end,duration}]。"""
    cmd = [
        "ffmpeg", "-i", str(path),
        "-vf", f"blackdetect=d={min_duration}:pix_th=0.10",
        "-an", "-f", "null", "-",
    ]
    p = _run(cmd, timeout=600)
    spans = []
    for line in p.stderr.splitlines():
        if "blackdetect" in line and "black_start" in line:
            rec: dict[str, float] = {}
            for token in line.split():
                if token.startswith(("black_start:", "black_end:", "black_duration:")):
                    k, v = token.split(":")
                    rec[k.replace("black_", "")] = float(v)
            if rec:
                spans.append(rec)
    return spans


def volumedetect(path: str | Path) -> dict[str, float | None]:
    """音量峰值/均值（dB），用于静音与响度判断。"""
    cmd = ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"]
    p = _run(cmd, timeout=600)
    result: dict[str, float | None] = {"mean_volume": None, "max_volume": None}
    for line in p.stderr.splitlines():
        if "mean_volume:" in line:
            result["mean_volume"] = float(line.split("mean_volume:")[1].split("dB")[0].strip())
        elif "max_volume:" in line:
            result["max_volume"] = float(line.split("max_volume:")[1].split("dB")[0].strip())
    return result


def extract_frames(path: str | Path, timestamps: list[float], out_dir: str | Path) -> list[Path]:
    """在指定时间点抽帧，返回图片路径列表。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, ts in enumerate(timestamps):
        target = out / f"frame_{i:03d}_t{ts:.2f}.jpg"
        cmd = [
            "ffmpeg", "-y", "-ss", f"{ts:.3f}", "-i", str(path),
            "-frames:v", "1", "-q:v", "3", str(target),
        ]
        p = _run(cmd)
        if p.returncode == 0 and target.exists():
            paths.append(target)
    return paths
