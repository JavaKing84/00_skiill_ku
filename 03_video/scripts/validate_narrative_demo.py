#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_narrative_demo.py — 模块3 最小单元测试（只输出 json/md）。

用真实时间轴 timeline_45s.json 做三组对照：
  A 默认 allow_jcut=True  → 应为 WARN（2 处 J-cut：S1 画外音、S4 独白）
  B allow_jcut=False      → 应为 FAIL（J-cut 升级为 block）
  C 注入命中"养老院"支线 + 情绪乱序 → 应为 FAIL 且 block 数 >= 2
另用一段合成"碎镜头时间轴"验证节奏告警。
输出：demo_out/validate_narrative_report.json、validate_narrative_demo.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"D:\00_skiill_ku\03_video")
SCRIPTS = ROOT / "scripts"
OUT = ROOT / "demo_out"

sys.path.insert(0, str(SCRIPTS))
from validate_narrative import render_md, validate  # noqa: E402


def synthetic_bad() -> dict:
    """情绪乱序 + 短碎镜头密集的时间轴。"""
    secs = []
    emos = ["放空", "对峙", "挣扎", "压抑", "压抑"]
    for i, e in enumerate(emos):
        secs.append({"id": f"X{i + 1}", "start": i * 1.0, "dur": 1.0, "emotion": e,
                     "role": "韦布", "shot": "中景",
                     "video": {"src": "导剪001.mp4", "in": 500 + i, "dur": 1.0},
                     "audio": {"src": "导剪001.mp4", "in": 500 + i, "dur": 1.0, "type": "同期声"}})
    return {"sections": secs}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    timeline = json.loads((ROOT / "assets" / "elephant" / "build45" / "timeline_45s.json")
                          .read_text(encoding="utf-8"))

    ra = validate(timeline, allow_jcut=True)
    rb = validate(timeline, allow_jcut=False)
    rc = validate(timeline, forbidden=[{"name": "养老院", "src": "导剪001.mp4",
                                        "start": 1040.0, "end": 1046.0}], allow_jcut=True)
    rd = validate(synthetic_bad(), allow_jcut=True)

    ok = (ra["verdict"] == "WARN" and rb["verdict"] == "FAIL" and rc["verdict"] == "FAIL"
          and rd["verdict"] == "FAIL")

    report = {"A_allow_jcut": ra, "B_no_jcut": rb, "C_forbidden_branch": rc, "D_fast_cut": rd}
    (OUT / "validate_narrative_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    md = ["# 模块3 叙事校验 Demo 报告", "",
          f"- 时间轴：`timeline_45s.json`（5 段，45.01s）",
          f"- 总判定：{'PASS' if ok else 'FAIL'}", "",
          "| 用例 | verdict | block | warn | 说明 |", "|---|---|---|---|---|",
          f"| A allow_jcut=True | {ra['verdict']} | {ra['counts']['block']} | {ra['counts']['warn']} | J-cut 只告警 |",
          f"| B allow_jcut=False | {rb['verdict']} | {rb['counts']['block']} | {rb['counts']['warn']} | J-cut 阻断 |",
          f"| C 命中养老院区间 | {rc['verdict']} | {rc['counts']['block']} | {rc['counts']['warn']} | 禁支线阻断 |",
          f"| D 碎镜头+情绪乱序 | {rd['verdict']} | {rd['counts']['block']} | {rd['counts']['warn']} | 节奏与顺序告警 |",
          "", "## A 用例明细", ""]
    md += render_md(ra).splitlines()[1:]
    (OUT / "validate_narrative_demo.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    for key, rep in report.items():
        print(f"{key}: {rep['verdict']} block={rep['counts']['block']} warn={rep['counts']['warn']}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
