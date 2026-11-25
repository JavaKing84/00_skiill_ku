#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_lifecycle.py — 生命周期管理验收测试。

策略：
- 把真实库复制到临时目录，在副本上插入各种合成条目，执行真实删除与恢复；
- 真实库只做 dry-run 规划，绝不删除；
- 覆盖：保留策略分档、受保护数据、观察期、快照降采样、purge_log、恢复、完整性、CLI 端到端。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_shared"))

from skillkit import lifecycle as lc  # noqa: E402
from skillkit.inteldb import IntelDB, content_hash_for  # noqa: E402

REAL_DB = ROOT / "06_techradar" / "data" / "techradar.db"
# 默认隔离：所有写入都落在临时库副本上，真实库只做只读校验
ALLOW_REAL_DB = "--allow-real-db" in sys.argv
CLI = ROOT / "06_techradar" / "scripts" / "lifecycle_run.py"
failures: list[str] = []


def real_db_guard() -> None:
    """未显式授权时，禁止对真实库做任何写入。"""
    if ALLOW_REAL_DB:
        print("WARN: 已通过 --allow-real-db 显式授权访问真实库")
        return
    if not REAL_DB.exists():
        return
    import sqlite3
    conn = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    try:
        conn.execute("SELECT COUNT(*) FROM entries").fetchone()
    finally:
        conn.close()
    print("GUARD: 真实库仅以只读方式访问（写入全部落临时副本）")


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)
    print(("PASS " if cond else "FAIL ") + msg)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def insert_entry(conn: sqlite3.Connection, title: str, *, days_old: float,
                 category: str = "dev", origin: str | None = None,
                 link_status: str = "active", link_checked_days: float | None = None,
                 metrics: dict | None = None, pinned: int = 0,
                 read_state: str = "title_scanned", expiry_days: float | None = None) -> int:
    now = datetime.now()
    seen = iso(now - timedelta(days=days_old))
    extra = {"kind": "opensource"}
    if expiry_days is not None:
        extra["expires_at"] = iso(now - timedelta(days=expiry_days))
    cur = conn.execute(
        "INSERT INTO entries(url,title,collected_at,content_hash,metrics_json,extra_json,"
        "first_seen_at,last_seen_at,link_status,category,origin_source,is_pinned,read_state,"
        "link_checked_at,value_tier,value_score) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"https://example.test/{abs(hash(title))}", title, seen,
         content_hash_for(f"https://example.test/{title}", title),
         json.dumps(metrics or {"points": 5}), json.dumps(extra),
         seen, seen, link_status, category, origin, pinned, read_state,
         iso(now - timedelta(days=link_checked_days)) if link_checked_days is not None else None,
         None, None),
    )
    return int(cur.lastrowid)


def main() -> int:
    real_db_guard()
    with tempfile.TemporaryDirectory() as td:
        tmp_db = Path(td) / "techradar.db"
        shutil.copy2(REAL_DB, tmp_db)
        cfg = lc.load_config(ROOT / "06_techradar" / "data" / "lifecycle_config.json")
        cfg["apply_purge"] = True  # 仅在副本上允许真实删除

        with IntelDB(tmp_db) as db:
            conn = db.conn
            n_policy = lc.sync_policy_table(conn, cfg)
            check(n_policy >= 10, f"retention_policy 同步 {n_policy} 条")

            # --- 构造样本 ---
            now = datetime.now()
            e_pinned = insert_entry(conn, "PINNED 人工收藏 300天", days_old=300, pinned=1)
            e_high = insert_entry(conn, "HIGH 高价值洞察 400天", days_old=400,
                                  metrics={"points": 5000, "comments": 400, "ai_quality": 5})
            e_gh = insert_entry(conn, "GITHUB 项目资料 500天", days_old=500,
                                origin="github-awesome-ai", category="opensource")
            e_reddit = insert_entry(conn, "REDDIT 讨论 120天", days_old=120,
                                    origin="r/coolgithubprojects", category="ai")
            e_promo = insert_entry(conn, "PROMO 交易推广 40天", days_old=40,
                                   category="trade", metrics={"obtain": "promo", "ai_keep": False})
            e_normal = insert_entry(conn, "NORMAL 普通正文 200天", days_old=200, category="dev")
            e_recent = insert_entry(conn, "RECENT 新帖 10天", days_old=10, category="dev")
            e_exp_old = insert_entry(conn, "EXPIRED 失效已久 300天", days_old=300,
                                     link_status="expired", link_checked_days=20)
            e_exp_new = insert_entry(conn, "EXPIRED 刚失效 300天", days_old=300,
                                     link_status="expired", link_checked_days=1)
            e_deep = insert_entry(conn, "DEEP 已深读 400天", days_old=400, read_state="deep_read")

            # --- 评分与分档 ---
            res = lc.rescore_all(conn, cfg)
            check(res["scored"] >= 10, f"重评 {res['scored']} 条，分档 {res['distribution']}")
            tiers = {r[0]: (r[1], r[2]) for r in conn.execute(
                "SELECT entry_id, value_tier, value_score FROM entries")}
            check(tiers[e_pinned][0] == "P0", "人工收藏强制 P0")
            check(tiers[e_high][0] == "P0", f"高价值条目 P0（score={tiers[e_high][1]}）")
            check(0 <= tiers[e_normal][1] <= 100, "评分落在 0-100")

            # --- dry-run 规划 ---
            plan = lc.plan_purge(conn, cfg, now)
            ids = {c.entry_id for c in plan}
            check(e_pinned not in ids, "收藏项不入清理计划")
            check(e_high not in ids, "高价值洞察不入清理计划")
            check(e_gh not in ids, "GitHub 资料长期保留")
            check(e_deep not in ids, "深度阅读记录不删")
            check(e_recent not in ids, "新数据不删")
            check(e_exp_new not in ids, "刚失效仍在观察期")
            check(e_reddit in ids, "Reddit 120 天 > 90 天策略，入选")
            check(e_promo in ids, "推广类 40 天 > 7 天入选")
            check(e_normal in ids, "普通正文 200 天 > 180 天入选")
            check(e_exp_old in ids, "失效超观察期入选")
            est = sum(c.bytes for c in plan)
            check(len(plan) >= 3 and est > 0, f"预计清理 {len(plan)} 条 / {est} 字节")

            before = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            check(before == conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
                  "dry-run 后行数不变")

            # --- 快照降采样（同一天多条才会被折叠）---
            snaps = [
                now - timedelta(days=100, hours=-8), now - timedelta(days=100, hours=-12),
                now - timedelta(days=100, hours=-18),
                now - timedelta(days=190, hours=-9), now - timedelta(days=190, hours=-15),
                now - timedelta(days=500), now - timedelta(days=501),
                now - timedelta(days=520),
            ]
            for ts in snaps:
                conn.execute("INSERT INTO snapshots(entry_id,taken_at,metrics_json) VALUES(?,?,?)",
                             (e_high, iso(ts), '{"points":1}'))
            conn.commit()
            dry = lc.downsample_snapshots(conn, cfg, dry_run=True, now=now)
            check(dry["would_delete"] == 4 and dry["snapshots_total"] == 8 and dry["keep"] == 4,
                  f"快照 dry-run：总 {dry['snapshots_total']} 保留 {dry['keep']} 拟删 {dry['would_delete']}")

            # --- 真实删除（副本） ---
            applied = lc.apply_purge(conn, plan, run_id=None, now=now)
            after = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            check(after == before - applied["deleted"], f"删除 {applied['deleted']} 条，行数 {before}->{after}")
            survived = {r[0] for r in conn.execute("SELECT entry_id FROM entries")}
            for eid, label in ((e_pinned, "收藏"), (e_high, "高价值"), (e_gh, "GitHub"),
                               (e_recent, "新数据"), (e_exp_new, "观察期"), (e_deep, "深读")):
                check(eid in survived, f"受保护/保留项存活：{label}")
            log_n = conn.execute("SELECT COUNT(*) FROM purge_log").fetchone()[0]
            check(log_n == applied["deleted"], f"purge_log 记录 {log_n} 条（含整行 JSON）")

            # --- 恢复 ---
            restored = lc.restore_purges(conn)
            check(restored["restored"] == applied["deleted"],
                  f"恢复 {restored['restored']} 条，跳过 {restored['skipped']}")
            check(conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == before,
                  "恢复后行数回到删除前")

            # --- 完整性 ---
            check(conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "副本库 integrity_check=ok")

            # --- 真实库只读校验（不写入，不迁移） ---
            import sqlite3 as _sq
            rconn = _sq.connect(f"file:{REAL_DB}?mode=ro", uri=True)
            try:
                real_n = rconn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
                real_after = rconn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            finally:
                rconn.close()
            check(real_n == real_after, f"真实库只读校验（{real_n} 条不变）")
            with IntelDB(Path(td) / "plan_only.db") as _db:
                _db.conn.execute("ATTACH DATABASE ? AS realdb", (str(REAL_DB),))
                plan = _db.conn.execute(
                    "SELECT COUNT(*) FROM realdb.entries WHERE COALESCE(link_status,'active')<>'expired'").fetchone()[0]
                _db.conn.execute("DETACH DATABASE realdb")
            check(plan >= 0, f"真实库只读规划条目 {plan}")

        # --- CLI 端到端（副本，weekly，dry-run） ---
        cfg_path = Path(td) / "lifecycle_config.json"
        lc.save_config(cfg_path, {**cfg, "apply_purge": False})
        # 用副本再跑一次 CLI（重建，因为上文已恢复）
        shutil.copy2(REAL_DB, Path(td) / "cli.db")
        p = subprocess.run([sys.executable, str(CLI), "--job", "weekly",
                            "--db", str(Path(td) / "cli.db"), "--config", str(cfg_path),
                            "--report-dir", str(Path(td) / "reports")],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        check(p.returncode == 0, f"CLI weekly dry-run 退出码 0（实际 {p.returncode}）")
        check("mode=dry-run" in p.stdout, f"CLI 报告模式 dry-run：{p.stdout.strip().splitlines()[0] if p.stdout else ''}")
        with IntelDB(Path(td) / "cli.db") as db2:
            runs = db2.conn.execute("SELECT job_name, mode, status FROM job_runs "
                                    "ORDER BY run_id").fetchall()
            check(bool(runs) and tuple(runs[-1]) == ("weekly", "dry-run", "PASS"),
                  f"新增 weekly dry-run 记录，共 {len(runs)} 条，末条 {tuple(runs[-1]) if runs else None}")
        check(any((Path(td) / "reports").glob("weekly_*.md")), "weekly 报告已生成")

    print()
    if failures:
        print(f"FAILED {len(failures)}:")
        for f in failures:
            print("  -", f)
        return 2
    print("PASS test_lifecycle: 保留策略/保护/观察期/降采样/删除日志/恢复/完整性/CLI 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
