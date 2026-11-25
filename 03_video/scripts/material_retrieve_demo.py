#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""material_retrieve_demo.py — 模块5 最小单元测试（只输出 csv/md，不解码视频）。

依赖前置产物（脚本会自动补跑）：
  demo_out/person_scan_result.csv + person_scan_detail.json   （导剪002 1625-1665）
  demo_out/shot_analyze_result_002.json                       （本 demo 现算）
  whisper_002.json                                            （E 盘旧转写，可缺省）

验证三组条件：
  A 于城出镜 + 特写 + 长镜头           → 必须有结果
  B 排除黑名单（老人）                  → 必须有结果
  C 台词关键词（从真实转写里取）        → 有转写时必须有结果
输出：demo_out/material_retrieve_result.csv、material_retrieve_demo.md
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\00_skiill_ku\03_video")
SCRIPTS = ROOT / "scripts"
OUT = ROOT / "demo_out"
RAW = ROOT / "assets" / "elephant" / "raw"
WHISPER = Path(r"E:\Trae_Video_Workspace\elephant_20261122\edit\whisper_002.json")

sys.path.insert(0, str(SCRIPTS))
from material_retrieve import load_person, load_shots, load_whisper, retrieve  # noqa: E402
from shot_analyze import analyze  # noqa: E402

SRC = "导剪002.mp4"


def ensure_person_inputs() -> None:
    if not (OUT / "person_scan_result.csv").exists():
        subprocess.run([sys.executable, str(SCRIPTS / "person_scan_demo.py")], check=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ensure_person_inputs()

    shots_path = OUT / "shot_analyze_result_002.json"
    if not shots_path.exists():
        shots = analyze(RAW / SRC, 1625, 1665)
        shots_path.write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")

    shots = load_shots([shots_path])
    persons = load_person({SRC: OUT / "person_scan_result.csv"},
                          {SRC: OUT / "person_scan_detail.json"})
    whisper = load_whisper([WHISPER]) if WHISPER.exists() else {}

    a = retrieve(shots, persons, whisper, SRC, need=["于城"], scales=["特写"], long_shot=True)
    b = retrieve(shots, persons, whisper, SRC, need=["于城"], exclude=["老人"])
    segs = whisper.get("002", [])
    inner = [s for s in segs if s["end"] > 1625 and s["start"] < 1665 and len(s["text"]) >= 2]
    kw = inner[0]["text"][:2] if inner else "阳台"
    c = retrieve(shots, persons, whisper, SRC, dialogue=[kw])

    # 主结果写约定文件名
    import csv
    with (OUT / "material_retrieve_result.csv").open("w", newline="", encoding="utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=["source", "start", "end", "shot_scale",
                                          "character_list", "dialogue_text", "confidence"])
        w.writeheader()
        w.writerows(a)

    ok = bool(a) and bool(b) and (bool(c) if segs else True)
    md = ["# 模块5 多模态素材检索 Demo 报告", "",
          f"- 素材：`{SRC}` 1625-1665；镜头数 {len(shots)}；人物窗口数 {len(persons.get('002', []))}",
          f"- whisper 台词段（该区间）：{len(inner)}",
          "", "| 查询 | 条件 | 命中 |", "|---|---|---|",
          f"| A | 于城 + 特写 + 长镜头 | {len(a)} |",
          f"| B | 于城 + 排除老人 | {len(b)} |",
          f"| C | 台词含『{kw}』 | {len(c)} |",
          "", "## A 结果明细", "",
          "| source | start | end | 景别 | 人物 | 台词 | 置信度 |",
          "|---|---|---|---|---|---|---|"]
    for r in a:
        md.append(f"| {r['source']} | {r['start']} | {r['end']} | {r['shot_scale']} | "
                  f"{r['character_list']} | {r['dialogue_text'][:40]} | {r['confidence']} |")
    md += ["", "> 局限：结果精度完全取决于上游人物扫描与镜头分析的精度；",
           "> 不做语义向量检索，同义词需以关键词列表表达（如 满洲里|大象）。"]
    (OUT / "material_retrieve_demo.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"A={len(a)} B={len(b)} C={len(c)} kw={kw} -> {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
