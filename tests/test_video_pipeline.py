#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_video_pipeline.py — 合成 fixture 上的视频全链路（分析→QC→dry-run）。

不使用任何真实版权素材或外部服务；fixture 由 ffmpeg lavfi 本地生成。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "03_video" / "scripts"


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None)


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        good = tdp / "good.mp4"
        bad = tdp / "silent_black_short.mp4"

        # fixture 1：彩条 + 正弦音（-9dB 防削顶），5s 854x480 30fps
        c1 = run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=854x480:rate=30:duration=5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
            "-af", "volume=-9dB",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(good),
        ])
        # fixture 2：纯黑、无音轨、2s（触发时长 FAIL + 无音轨）
        c2 = run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=black:size=854x480:rate=30:duration=2",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(bad),
        ])
        if c1.returncode != 0 or c2.returncode != 0 or not good.exists() or not bad.exists():
            print("FAIL fixture 生成失败", c1.stderr[-300:], c2.stderr[-300:])
            return 2

        # 1. 参考分析
        ana_dir = tdp / "analysis"
        r1 = run([sys.executable, str(SCRIPTS / "reference_analyze.py"),
                  "--video", str(good), "--out", str(ana_dir)])
        style_p = ana_dir / "reference_style.json"
        if r1.returncode != 0 or not style_p.exists():
            failures.append(f"reference_analyze 失败: {r1.stdout} {r1.stderr[-300:]}")
        else:
            style = json.loads(style_p.read_text(encoding="utf-8"))
            if style["probe"]["video"]["width"] != 854 or style["shot_count"] < 1:
                failures.append("reference_style 元信息异常")
            if not (ana_dir / "reference_timeline.csv").exists() or not style["frames_extracted"]:
                failures.append("timeline 或抽帧缺失")

        # 2. 好片 QC 应 PASS（退出码 0）
        qc_good = tdp / "qc_good"
        r2 = run([sys.executable, str(SCRIPTS / "video_qc.py"),
                  "--video", str(good), "--out", str(qc_good)])
        if r2.returncode != 0:
            failures.append(f"好片 QC 未 PASS，退出码 {r2.returncode}: {r2.stdout}")
        else:
            verdict = json.loads((qc_good / "video_qc.json").read_text(encoding="utf-8"))["verdict"]
            if verdict != "PASS":
                failures.append(f"好片 verdict={verdict}，期望 PASS")

        # 3. 坏片 QC 应 FAIL（退出码 2），且问题清单非空
        qc_bad = tdp / "qc_bad"
        r3 = run([sys.executable, str(SCRIPTS / "video_qc.py"),
                  "--video", str(bad), "--out", str(qc_bad)])
        if r3.returncode != 2:
            failures.append(f"坏片未被判 FAIL，退出码 {r3.returncode}")
        else:
            bad_json = json.loads((qc_bad / "video_qc.json").read_text(encoding="utf-8"))
            if not bad_json["findings"]:
                failures.append("坏片问题清单为空")

        # 4. 发布 dry-run：只产文件，无发布动作
        prev = tdp / "publish_preview.md"
        r4 = run([sys.executable, str(SCRIPTS / "publish_preview.py"),
                  "--video", str(good), "--platform", "douyin", "--account", "13800001234",
                  "--title", "测试", "--tags", "t1,t2", "--out", str(prev)])
        if r4.returncode != 0 or not prev.exists():
            failures.append("publish_preview 失败")
        else:
            text = prev.read_text(encoding="utf-8")
            payload = json.loads(prev.with_suffix(".json").read_text(encoding="utf-8"))
            if "DRY-RUN" not in text or payload["mode"] != "DRY_RUN_ONLY":
                failures.append("dry-run 标记缺失")
            if "13800001234" in text:
                failures.append("账号未脱敏")

    if failures:
        print("FAIL", failures)
        return 2
    print("PASS test_video_pipeline: fixture生成/参考分析/好片PASS/坏片FAIL/dry-run脱敏 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
