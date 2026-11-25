#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quality_check_demo.py — 模块7 综合巡检最小单元测试（只输出 md/json，不渲染视频）。

用真实 45s 时间轴跑一次完整综合巡检：
  人物出镜 + 镜头节奏 + 叙事/J-cut + 音频指标 + 素材边界 → quality_report.md
再用注入「养老院」禁支线区间做一次对照，验证 block 会追加。

自检断言：
  - 报告文件生成且非空
  - S2 命中黑名单（001@1042-1049 画面为老年男性=王金候选，台词却是黄玲）
  - S3 命中目标主角于城
  - 存在 J-cut 告警（S1 画外音 / S4 独白）
  - 注入禁支线后 block 数增加

输出：demo_out/quality_report.md、quality_report.json、quality_check_demo.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"D:\00_skiill_ku\03_video")
SCRIPTS = ROOT / "scripts"
OUT = ROOT / "demo_out"
RAW = ROOT / "assets" / "elephant" / "raw"
GALLERY = ROOT / "assets" / "elephant" / "faces"
TIMELINE = ROOT / "assets" / "elephant" / "build45" / "timeline_45s.json"
BGM = ROOT / "assets" / "elephant" / "bgm" / "志铭.m4a"

sys.path.insert(0, str(SCRIPTS))
from quality_check_all import run  # noqa: E402
from validate_narrative import validate  # noqa: E402


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report = run(TIMELINE, RAW, GALLERY, OUT, forbidden=None, allow_jcut=True,
                 bgm=BGM if BGM.exists() else None, blacklist_level="block")

    secs = {p["section"]: p for p in report["person"]["sections"]}
    s2_black = bool(secs.get("S2", {}).get("blacklist"))
    s3_target = "于城" in (secs.get("S3", {}).get("target") or [])
    jcut_warn = [i for i in report["issues"]
                 if i["error_level"] == "warn" and "J-cut" in i["message"]]
    shots_ok = report["shots"]["count"] >= 3
    md_ok = (OUT / "quality_report.md").stat().st_size > 500

    tl = json.loads(TIMELINE.read_text(encoding="utf-8"))
    b = validate(tl, report["shots"]["list"],
                 [{"name": "养老院", "src": "导剪001.mp4", "start": 1040.0, "end": 1046.0}],
                 None, True)
    forbidden_block = any(i["message"].startswith("命中禁止支线") for i in b["issues"])
    forbidden_added = (forbidden_block
                       and not any(i["message"].startswith("命中禁止支线") for i in report["issues"]))

    ok = all([md_ok, s2_black, s3_target, bool(jcut_warn), shots_ok, forbidden_added])

    md = ["# 模块7 综合质量巡检 Demo 报告", "",
          f"- 时间轴：`timeline_45s.json`（计划 {report['duration_plan']}s / 实排 {report['duration_sum']}s）",
          f"- 总结论：**{report['verdict']}**（block {report['counts']['block']} / warn {report['counts']['warn']}）",
          f"- 自检：{'PASS' if ok else 'FAIL'}", "",
          "| 自检项 | 结果 | 证据 |", "|---|---|---|",
          f"| 报告文件生成 | {'PASS' if md_ok else 'FAIL'} | quality_report.md |",
          f"| S2 黑名单命中 | {'PASS' if s2_black else 'FAIL'} | {secs.get('S2', {}).get('blacklist') or '未命中'} |",
          f"| S3 目标主角命中 | {'PASS' if s3_target else 'FAIL'} | {secs.get('S3', {}).get('target') or '未命中'} |",
          f"| J-cut 告警 | {'PASS' if jcut_warn else 'FAIL'} | {len(jcut_warn)} 条 |",
          f"| 镜头语义产出 | {'PASS' if shots_ok else 'FAIL'} | {report['shots']['count']} 镜 |",
          f"| 注入禁支线后新增 block | {'PASS' if forbidden_added else 'FAIL'} | "
          f"注入后新增 {sum(1 for i in b['issues'] if i['message'].startswith('命中禁止支线'))} 条 |", "",
          "## 人物出镜汇总", "",
          "| 段落 | 目标 | 黑名单 | 人脸数 | 相似度 | 判定 |", "|---|---|---|---|---|---|"]
    for p in report["person"]["sections"]:
        md.append(f"| {p['section']} | {','.join(p['target']) or '-'} | "
                  f"{','.join(p['blacklist']) or '-'} | {p['face_count']} | "
                  f"{p['confidence']} | {p['verdict']} |")
    md += ["", "## 说明",
           "- S2 是典型的「音频说话人 ≠ 画面人物」：台词属于黄玲，画面却是老年男性（王金候选）。",
           "- S4 的 001@1049.4 片段同样检出了该老年男性（相似度很高），说明时间轴里这段的"
           " role=黄玲 标注与实际画面不符，应换素材或降级放行。",
           "- 如剧情需要保留该画面，可用 `--blacklist-level warn` 降级为告警。",
           "- 完整报告见 `demo_out/quality_report.md`；本 demo 未生成任何视频文件。"]
    (OUT / "quality_check_demo.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"verdict={report['verdict']} block={report['counts']['block']} warn={report['counts']['warn']}")
    print(f"S2_blacklist={s2_black} S3_target={s3_target} jcut_warn={len(jcut_warn)} "
          f"shots={report['shots']['count']} forbidden_block_added={forbidden_added}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
