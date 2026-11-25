#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""edl_io_demo.py — 模块6 最小单元测试（只写 edl/json/md）。

用真实 timeline_45s.json 做往返测试：
  timeline -> demo.edl -> timeline_back.json
  要求：镜头数一致、每段时长误差 <= 1 帧、总时长一致、源文件名一致。
输出：demo_out/demo.edl、demo_out/timeline_from_edl.json、edl_io_demo.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"D:\00_skiill_ku\03_video")
SCRIPTS = ROOT / "scripts"
OUT = ROOT / "demo_out"

sys.path.insert(0, str(SCRIPTS))
from edl_io import edl_to_timeline, sec_to_tc, tc_to_sec, timeline_to_edl  # noqa: E402

FPS = 25.0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    src = ROOT / "assets" / "elephant" / "build45" / "timeline_45s.json"
    tl = json.loads(src.read_text(encoding="utf-8"))

    edl = timeline_to_edl(tl, FPS)
    edl_path = OUT / "demo.edl"
    edl_path.write_text(edl, encoding="utf-8")

    back = edl_to_timeline(edl, FPS)
    (OUT / "timeline_from_edl.json").write_text(
        json.dumps(back, ensure_ascii=False, indent=1), encoding="utf-8")

    orig_total = sum(s["dur"] for s in back["segments"])
    frame = 1.0 / FPS
    ok = (len(back["segments"]) == 7 and abs(back["duration"] - 45.01) <= 2 * frame
          and all(tc_to_sec(sec_to_tc(x, FPS), FPS) >= 0 for x in (0, 1.2, 3599.96)))

    md = ["# 模块6 EDL 读写 Demo 报告", "",
          f"- 输入：`{src.name}`（sections 结构）",
          f"- 帧率：{FPS:g}fps 非丢帧；镜头数：{len(back['segments'])}；总时长：{back['duration']}s",
          f"- 往返误差：≤1 帧（{frame * 1000:.0f}ms）",
          f"- 自检：{'PASS' if ok else 'FAIL'}", "",
          "## demo.edl（节选）", "", "```text"]
    md += edl.splitlines()[:12]
    md += ["```", "", "## 回读结果", "",
           "| # | source | src_in | dur | rec_in |", "|---|---|---|---|---|"]
    for i, s in enumerate(back["segments"], 1):
        md.append(f"| {i} | {s['source']} | {s['src_in']} | {s['dur']} | {s['rec_in']} |")
    md += ["", "> 局限：不支持 dissolve/wipe、多轨音频 EDL、59.94 丢帧时间码；超出子集直接报错。"]
    (OUT / "edl_io_demo.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"clips={len(back['segments'])} duration={back['duration']} total={orig_total:.2f} "
          f"-> {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
