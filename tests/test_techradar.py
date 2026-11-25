#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_techradar.py — SQLite 情报库：建表、去重、读取状态、分析台账。"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_shared"))
from skillkit.inteldb import IntelDB  # noqa: E402


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        with IntelDB(db_path) as db:
            v1 = db.add_entry("Hacker News (public fallback)", "hn",
                              "https://news.ycombinator.com/item?id=1", "Hot thing",
                              metrics={"points": 100})
            v2 = db.add_entry("Hacker News (public fallback)", "hn",
                              "https://news.ycombinator.com/item?id=1", "Hot thing")
            v3 = db.add_entry("GitHub Search (public fallback)", "github",
                              "https://github.com/x/y", "x/y")
            if (v1, v2, v3) != ("inserted", "duplicate", "inserted"):
                failures.append(f"去重行为异常: {v1},{v2},{v3}")

            updated = db.mark_read("https://github.com/x/y", "body_read")
            if updated != 1:
                failures.append("读取状态更新失败")

            iid = db.add_insight("demo-project", "可以组合 A+B 做端侧推理",
                                 [{"url": "https://github.com/x/y", "note": "证据"}], "high")
            if not isinstance(iid, int):
                failures.append("insight 写入失败")

            run_id = db.start_run("端侧推理选型")
            db.finish_run(run_id, {"hn": {"scanned": 1, "read": 0}, "github": {"scanned": 1, "read": 1}})
            stats = db.stats()
            if stats["entries"] != 2 or stats["insights"] != 1 or stats["runs"] != 1:
                failures.append(f"统计异常: {stats}")

        # 持久化重开
        with IntelDB(db_path) as db2:
            if db2.stats()["entries"] != 2:
                failures.append("重开后数据丢失")

    if failures:
        print("FAIL", failures)
        return 2
    print("PASS test_techradar: 建表/URL去重/状态机/insight/run台账/持久化 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
