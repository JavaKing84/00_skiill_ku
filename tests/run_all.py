#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_all.py — 统一测试运行器（13 套）。

- 逐套运行 tests/ 下的测试，日志落 `_logs/test_run_<ts>/`；
- `skill_sync_check` / `test_remediation` 中已知的 P0-1 壳版本声明标记为
  `PENDING (Expected Warning)`，不按系统故障处理；
- 只有 FAIL 才让整体退出码非 0；
- 生成 `_reports/TEST_REPORT_<ts>.md` 与 `.json`。

用法：
  python tests/run_all.py            # 全量
  python tests/run_all.py --only test_techradar.py,test_lifecycle.py
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
LOG_DIR = ROOT / "_logs"
REPORT_DIR = ROOT / "_reports"

SUITES = [
    "skill_sync_check.py",
    "test_skillkit_contract.py",
    "test_techradar.py",
    "test_registry.py",
    "test_lifecycle.py",
    "test_triggers.py",
    "test_crawl_tools.py",
    "test_video_pipeline.py",
    "test_remediation.py",
    "test_quality_review.py",
    "test_dual_channel.py",
    "test_scenarios.py",
    "test_zcl_integration.py",
]
# 允许带 PENDING 标记通过的套件（P0-1 暂缓项）
PENDING_ALLOWED = {"skill_sync_check.py", "test_remediation.py"}


def run_one(name: str, log_dir: Path, timeout: int = 900) -> dict:
    path = TESTS / name
    t0 = time.time()
    proc = subprocess.run([sys.executable, str(path)], capture_output=True, text=True,
                          cwd=str(ROOT), timeout=timeout)
    out = (proc.stdout or "") + (proc.stderr or "")
    (log_dir / f"{name}.log").write_text(out, encoding="utf-8")
    pending = proc.returncode == 0 and "PENDING" in out and name in PENDING_ALLOWED
    status = "PENDING" if pending else ("PASS" if proc.returncode == 0 else "FAIL")
    return {
        "suite": name,
        "status": status,
        "exit": proc.returncode,
        "seconds": round(time.time() - t0, 1),
        "tail": out.strip().splitlines()[-12:],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="逗号分隔的测试文件名")
    args = ap.parse_args()
    suites = [s.strip() for s in args.only.split(",") if s.strip()] or SUITES

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = LOG_DIR / f"test_run_{ts}"
    log_dir.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for name in suites:
        print(f"\n===== {name} =====", flush=True)
        try:
            r = run_one(name, log_dir)
        except subprocess.TimeoutExpired:
            r = {"suite": name, "status": "FAIL", "exit": "TIMEOUT", "seconds": 900,
                 "tail": ["TIMEOUT > 900s"]}
        results.append(r)
        print(f"{r['status']} {name} exit={r['exit']} {r['seconds']}s", flush=True)
        for line in r["tail"]:
            print("  " + line, flush=True)

    counts = {k: sum(1 for r in results if r["status"] == k)
              for k in ("PASS", "PENDING", "FAIL")}
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "log_dir": str(log_dir),
        "counts": counts,
        "results": results,
    }
    (REPORT_DIR / f"TEST_REPORT_{ts}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 全量测试报告 {ts}",
        "",
        f"- 运行器：`tests/run_all.py`",
        f"- 日志：`{log_dir}`",
        f"- 结果：PASS {counts['PASS']} / PENDING {counts['PENDING']} / FAIL {counts['FAIL']}",
        "",
        "| 套件 | 状态 | 退出码 | 耗时(s) |",
        "|---|---|---:|---:|",
    ]
    for r in results:
        lines.append(f"| `{r['suite']}` | {r['status']} | {r['exit']} | {r['seconds']} |")
    lines += ["", "> PENDING = 已知的 P0-1 壳版本声明暂缓项（Expected Warning），不是系统故障。", ""]
    (REPORT_DIR / f"TEST_REPORT_{ts}.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"\nSUMMARY: PASS={counts['PASS']} PENDING={counts['PENDING']} FAIL={counts['FAIL']}")
    print(f"REPORT: {REPORT_DIR / f'TEST_REPORT_{ts}.md'}")
    return 0 if counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
