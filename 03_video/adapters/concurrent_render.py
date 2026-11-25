"""concurrent_render.py — 多进程切片渲染 + concat 拼接，压榨 CPU 多核。

montage_edit.py 原本 34 段串行渲染（11.5 分钟）。本模块把互不依赖的片段
扔进进程池并行渲染（默认 workers = CPU 核数），再 ffmpeg concat 拼接。

接口：render_segments(segments, workdir, out, encoder) -> dict
  segments: [{"index":i, "cmd":[ffmpeg args...] 或 "input":"...","filter":"..."}]
为通用起见，这里实现"给定每段的 ffmpeg 命令列表，并行执行 + 拼接"。

CLI（示例，需配合主流程传入段命令）：
  python adapters/concurrent_render.py --manifest segs.json --out final.mp4
  manifest: {"segments":[{"out":"p01.mp4","cmd":["-i","a.mp4","-t","5","p01.mp4"]}, ...], "concat":["p01.mp4",...]}
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .ffmpeg_utils import resolve_ffmpeg, run_ffmpeg


def _run_one(seg: dict) -> dict:
    """子进程：执行单段 ffmpeg 命令。seg 必须含 out 和 cmd（不含 ffmpeg 本身）。"""
    cmd = [resolve_ffmpeg(), "-y", "-hide_banner"] + seg["cmd"] + [seg["out"]]
    import subprocess
    cp = subprocess.run(cmd, capture_output=True, text=True)
    return {"index": seg.get("index"), "out": seg["out"],
            "ok": cp.returncode == 0, "err": cp.stderr[-300:] if cp.returncode else ""}


def render_segments(segments: list[dict], concat_order: list[str], out: str,
                    workers: int | None = None) -> dict:
    workers = workers or os.cpu_count() or 4
    t0 = time.time()
    results = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_run_one, s): s.get("index") for s in segments}
        for fut in as_completed(futs):
            r = fut.result()
            results[r["index"]] = r
    failed = [i for i, r in results.items() if not r["ok"]]
    if failed:
        return {"ok": False, "failed_segments": failed, "results": results}
    # concat
    listfile = Path(out).with_suffix(".concat.txt")
    listfile.write_text("".join(f"file '{Path(p).as_posix()}'\n" for p in concat_order),
                        encoding="utf-8")
    cp = run_ffmpeg(["-y", "-hide_banner", "-f", "concat", "-safe", "0",
                     "-i", str(listfile), "-c", "copy", out])
    ok = cp.returncode == 0
    return {"ok": ok, "segments": len(segments), "workers": workers,
            "output": out, "elapsed_sec": round(time.time() - t0, 2),
            "concat_err": cp.stderr[-300:] if not ok else ""}


def main() -> int:
    ap = argparse.ArgumentParser(description="多进程切片渲染 + concat")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=0)
    a = ap.parse_args()
    man = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    res = render_segments(man["segments"], man["concat"], a.out,
                          a.workers or None)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
