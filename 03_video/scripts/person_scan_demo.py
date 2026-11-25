#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""person_scan_demo.py — 模块1 最小单元测试（仅输出分析数据，不渲染视频）。

自检逻辑：
  A 段（导剪002 1625-1665，已核验为于城侧脸近景）→ 应命中 target、不命中 blacklist
  B 段（导剪001 1038-1060，已核验画面为老年男性）→ 应命中 blacklist、不命中 target
输出：demo_out/person_scan_result.csv、person_scan_result_blacklist.csv、
      person_scan_detail.json、person_scan_demo.md
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\00_skiill_ku\03_video")
SCRIPTS = ROOT / "scripts"
OUT = ROOT / "demo_out"
RAW = ROOT / "assets" / "elephant" / "raw"
GALLERY = ROOT / "assets" / "elephant" / "faces"
SEED = ROOT / "assets" / "elephant" / "faces_seed.json"

sys.path.insert(0, str(SCRIPTS))
from person_scan import FaceEngine, load_gallery, scan  # noqa: E402


def run(name: str, video: str, start: float, end: float, out_csv: Path, detail: Path):
    gal = load_gallery(GALLERY, FaceEngine(0.7, 0.3))
    rows, det = scan(RAW / video, start, end, gal, window=4.0, fps=1.0)
    with out_csv.open("w", newline="", encoding="utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=["start", "end", "target_person_hit",
                                          "blacklist_person_hit", "face_count", "confidence"])
        w.writeheader()
        w.writerows(rows)
    detail.write_text(json.dumps({"clip": name, "video": video, "start": start, "end": end,
                                  "windows": det}, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if not (GALLERY / "index.json").exists():
        print("[demo] 参考库不存在，先用已核验镜头建库 ...")
        subprocess.run([sys.executable, str(SCRIPTS / "person_scan.py"), "--build-gallery",
                        "--spec", str(SEED), "--video-dir", str(RAW), "--gallery", str(GALLERY)],
                       check=True)

    a = run("A_于城片段", "导剪002.mp4", 1625, 1665,
            OUT / "person_scan_result.csv", OUT / "person_scan_detail.json")
    b = run("B_老人片段", "导剪001.mp4", 1038, 1060,
            OUT / "person_scan_result_blacklist.csv", OUT / "person_scan_detail_blacklist.json")

    def ratio(rows, key):
        return sum(r[key] for r in rows) / max(1, len(rows))

    ta, ba = ratio(a, "target_person_hit"), ratio(a, "blacklist_person_hit")
    tb, bb = ratio(b, "target_person_hit"), ratio(b, "blacklist_person_hit")
    ok_a = ta >= 0.8 and ba <= 0.2
    ok_b = bb >= 0.8 and tb <= 0.2

    md = ["# 模块1 人物检索 Demo 报告", "",
          f"- 参考库：`{GALLERY}`（index.json 缓存 embedding）",
          "- 扫描窗口：4s，抽帧 1fps，相似度阈值 0.363", "",
          "| 片段 | 窗口数 | target 命中率 | blacklist 命中率 | 自检 |",
          "|---|---|---|---|---|",
          f"| A 导剪002 1625-1665（于城） | {len(a)} | {ta:.0%} | {ba:.0%} | {'PASS' if ok_a else 'FAIL'} |",
          f"| B 导剪001 1038-1060（老人） | {len(b)} | {tb:.0%} | {bb:.0%} | {'PASS' if ok_b else 'FAIL'} |",
          "", "## 明细（A 段）", "",
          "| start | end | target | blacklist | face_count | confidence |",
          "|---|---|---|---|---|---|"]
    for r in a:
        md.append(f"| {r['start']} | {r['end']} | {r['target_person_hit']} | "
                  f"{r['blacklist_person_hit']} | {r['face_count']} | {r['confidence']} |")
    md += ["", "> 局限：背光、强侧脸、遮挡、远距离小人脸会漏检/误检；阈值需按片源重标定。"]
    (OUT / "person_scan_demo.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"A: target {ta:.0%} blacklist {ba:.0%} -> {'PASS' if ok_a else 'FAIL'}")
    print(f"B: target {tb:.0%} blacklist {bb:.0%} -> {'PASS' if ok_b else 'FAIL'}")
    print(f"outputs -> {OUT}")
    return 0 if (ok_a and ok_b) else 1


if __name__ == "__main__":
    raise SystemExit(main())
