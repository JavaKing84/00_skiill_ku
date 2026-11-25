"""ffmpeg 工具：统一解析 ffmpeg/ffprobe 路径 + 安全执行。

纯 CPU 无 GPU 环境下，ffmpeg 原生滤镜（scene / mpdecimate / delogo / scale）
是性能底座——比 Python 逐帧循环快数倍到数十倍。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

# 解析顺序：环境变量 FFMPEG_BIN > PATH > 常见安装位置
_CANDIDATES = [
    r"D:\tools\ffmpeg\bin\ffmpeg.exe",
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
]


def resolve_ffmpeg() -> str:
    env = os.environ.get("FFMPEG_BIN")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    for c in _CANDIDATES:
        if Path(c).exists():
            return c
    raise FileNotFoundError("未找到 ffmpeg，请设置环境变量 FFMPEG_BIN 或将其加入 PATH")


def resolve_ffprobe() -> str:
    ffmpeg = resolve_ffmpeg()
    ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe"))
    if Path(ffprobe).exists():
        return ffprobe
    found = shutil.which("ffprobe")
    if found:
        return found
    raise FileNotFoundError("未找到 ffprobe")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """执行 ffmpeg 命令，默认捕获 stderr 用于诊断。"""
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(cmd, **kw)


def probe_duration(video: str | Path) -> float:
    cp = run([resolve_ffprobe(), "-v", "error", "-show_entries", "format=duration",
              "-of", "json", str(video)])
    return float(json.loads(cp.stdout)["format"]["duration"])


def run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    return run([resolve_ffmpeg()] + args)
