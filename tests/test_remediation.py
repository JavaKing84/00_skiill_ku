#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_remediation.py — 本轮整改的验收测试（全部在临时库/临时目录执行）。

覆盖：规则结构、canonical frontmatter、客户端壳同步、FTS5 全文、时间过滤、标签过滤、
来源过滤、关联检索、read_state 状态机、scheduler status 只读、渲染产出、BGM 授权闸门、
数据库完整性、生命周期四周期隔离运行。
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
sys.path.insert(0, str(ROOT / "tests"))

from skillkit.inteldb import IntelDB, content_hash_for  # noqa: E402
from skillkit import search as sx  # noqa: E402

REAL_DB = ROOT / "06_techradar" / "data" / "techradar.db"
CLI = ROOT / "06_techradar" / "scripts" / "lifecycle_run.py"
SCHED = ROOT / "06_techradar" / "scripts" / "scheduler.py"
RENDER = ROOT / "03_video" / "scripts" / "render.py"
failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)
    print(("PASS " if cond else "FAIL ") + msg)


def seed(conn) -> None:
    """写入带不同标签/来源/时间的合成条目（仅临时库）。"""
    now = datetime.now()
    def add(title, url, days, category, origin, tags, metrics=None):
        seen = (now - timedelta(days=days)).isoformat(timespec="seconds")
        cur = conn.execute(
            "INSERT INTO entries(url,title,collected_at,content_hash,metrics_json,extra_json,"
            "first_seen_at,last_seen_at,link_status,category,origin_source,published_at,read_state) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (url, title, seen, content_hash_for(url, title), json.dumps(metrics or {}),
             json.dumps({"kind": "opensource", "content": f"正文 {title} robot llama finetune"}),
             seen, seen, "active", category, origin, seen, "title_scanned"))
        eid = int(cur.lastrowid)
        for t in tags:
            conn.execute("INSERT OR IGNORE INTO tags(name) VALUES(?)", (t,))
            tid = conn.execute("SELECT tag_id FROM tags WHERE name=?", (t,)).fetchone()[0]
            conn.execute("INSERT OR IGNORE INTO entry_tags(entry_id,tag_id) VALUES(?,?)", (eid, tid))
        return eid

    add("AlphaRobot VLA 框架", "https://ex.test/alpha-robot", 3, "ai", "r/robotics", ["robot", "vla"],
        {"points": 900, "ai_quality": 5})
    add("BetaLlama 量化小模型", "https://ex.test/beta-llama", 40, "opensource", "github-awesome-ai",
        ["model", "quant"], {"stars": 3000})
    add("GammaOld 旧资讯", "https://ex.test/gamma", 200, "dev", "rss-ithome", ["news"], {"points": 5})
    add("DeltaRobot 端侧推理", "https://ex.test/delta", 5, "dev", "radar.zichuanlan.top", ["robot"],
        {"points": 120})
    conn.commit()
    return conn


def main() -> int:
    # ---- 1. 规则结构与同步 ----
    p = subprocess.run([sys.executable, str(ROOT / "tests" / "skill_sync_check.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    pending = "PENDING" in (p.stdout or "")
    if p.returncode == 0:
        check(True, "canonical/壳/规则一致性：PASS"
                    + ("（PENDING: 壳版本声明 2 项，按 Expected Warning 处理）" if pending else ""))
    else:
        check(False, f"canonical/壳/规则一致性：exit={p.returncode}")
        print(p.stdout[-1500:])

    # ---- 2. 临时库上的检索能力 ----
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        db = tdp / "t.db"
        shutil.copy2(REAL_DB, db)
        with IntelDB(db) as d:
            seed(d.conn)
            n = sx.rebuild_fts(d.conn)
            check(n > 0, f"FTS 索引回填 {n} 条")

        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        r1 = sx.query_entries(conn, text="robot", limit=10)
        check(r1["engine"] == "fts5", f"FTS5 全文检索 engine={r1['engine']}")
        check(r1["count"] >= 2, f"FTS 命中 {r1['count']} 条（robot）")

        r2 = sx.query_entries(conn, text="robot", engine="like", limit=10)
        check(r2["engine"] == "like" and r2["count"] >= 2, f"LIKE 降级可用 hits={r2['count']}")

        since_str = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        r3 = sx.query_entries(conn, since=since_str, limit=50)
        # 时间过滤以 COALESCE(published_at, first_seen_at) 为准（与 SQL 过滤语义一致）
        eff = [(r.get("published_at") or r.get("first_seen_at") or "")[:10] for r in r3["rows"]]
        check(all(e >= since_str for e in eff if e),
              f"时间过滤只返回窗口内条目（{r3['count']} 条，窗口起点 {since_str}）")

        r4 = sx.query_entries(conn, tags=["robot"], limit=20)
        check(r4["count"] >= 2 and all("robot" in r["tags"] for r in r4["rows"]),
              f"标签过滤命中 {r4['count']} 条且均带 robot 标签")

        r5 = sx.query_entries(conn, sources=["github-awesome-ai"], limit=20)
        check(r5["count"] >= 1 and all(r["origin_source"] == "github-awesome-ai" for r in r5["rows"]),
              f"来源过滤命中 {r5['count']} 条")

        first_id = conn.execute("SELECT entry_id FROM entries WHERE title LIKE 'AlphaRobot%'").fetchone()[0]
        # 显式登记一条真实关联（不伪造：两条都是本次种入的真实条目）
        with IntelDB(db) as d:
            second_id = d.conn.execute(
                "SELECT entry_id FROM entries WHERE title LIKE 'DeltaRobot%'").fetchone()[0]
            d.link_relation(first_id, second_id, "combo", "测试组合关系")
        r6 = sx.query_entries(conn, related_to=first_id, limit=20)
        check(r6["count"] >= 1, f"关联检索命中 {r6['count']} 条")
        check(any(r["entry_id"] == second_id for r in r6["rows"]), "关联检索返回被关联条目")

        r7 = sx.query_entries(conn, text="robot", tags=["vla"], limit=20)
        check(r7["count"] >= 1, f"多条件组合命中 {r7['count']} 条")
        conn.close()

        # ---- 3. read_state 状态机 ----
        with IntelDB(db) as d:
            url = "https://ex.test/alpha-robot"
            s1 = d.mark_read_state(url, "content_fetched")
            s2 = d.mark_read_state(url, "content_read")
            s3 = d.mark_read_state(url, "analyzed")
            s4 = d.mark_read_state(url, "title_scanned")   # 试图降级
            check(s1 == "content_fetched" and s2 == "content_read" and s3 == "analyzed",
                  f"状态机只前进：{s1}→{s2}→{s3}")
            check(s4 == "analyzed", f"状态机拒绝降级（返回 {s4}）")
            try:
                d.mark_read_state(url, "not_a_state")
                check(False, "非法状态应被拒绝")
            except ValueError:
                check(True, "非法状态被拒绝")

        # ---- 4. scheduler status 只读 ----
        before_mtime = REAL_DB.stat().st_mtime
        before_rows = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True).execute(
            "SELECT COUNT(*) FROM entries").fetchone()[0]
        p2 = subprocess.run([sys.executable, str(SCHED), "--action", "status"],
                            capture_output=True, text=True, cwd=str(ROOT), timeout=180)
        after_mtime = REAL_DB.stat().st_mtime
        after_rows = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True).execute(
            "SELECT COUNT(*) FROM entries").fetchone()[0]
        check(p2.returncode == 0, f"scheduler status 退出码 {p2.returncode}")
        check(before_mtime == after_mtime, f"status 未改真实库 mtime（{before_mtime} == {after_mtime}）")
        check(before_rows == after_rows, f"status 未改真实库行数（{before_rows} == {after_rows}）")

        # ---- 5. 生命周期四周期隔离运行 ----
        for job in ("daily", "weekly", "monthly", "quarterly"):
            cfgp = tdp / f"cfg_{job}.json"
            cfgp.write_text(json.dumps({"apply_purge": False, "retention_days": {}, "low_value_categories": [],
                                        "observation_days": 14, "snapshots": {"raw_days": 90, "daily_keep_days": 400},
                                        "project_profiles": {}, "value_weights": {},
                                        "tier_thresholds": {"P0": 85, "P1": 65, "P2": 40}}), encoding="utf-8")
            pj = subprocess.run([sys.executable, str(CLI), "--job", job, "--db", str(db),
                                 "--config", str(cfgp), "--report-dir", str(tdp / "rep"),
                                 "--no-collect"],
                                capture_output=True, text=True, cwd=str(ROOT), timeout=600)
            check(pj.returncode == 0 and f"mode=dry-run" in pj.stdout,
                  f"生命周期 {job} 隔离运行：exit={pj.returncode} {pj.stdout.strip().splitlines()[0] if pj.stdout else ''}")

        # ---- 6. 渲染与 BGM 闸门（真实产物） ----
        a = tdp / "a.mp4"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=4",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-af", "volume=-9dB",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(a)],
                       capture_output=True, text=True, timeout=300)
        out = tdp / "out.mp4"
        pr = subprocess.run([sys.executable, str(RENDER), "--inputs", str(a), "--out", str(out),
                             "--aspect", "9:16", "--subtitle", "整改测试字幕", "--qc"],
                            capture_output=True, text=True, cwd=str(ROOT), timeout=900)
        ok = pr.returncode == 0 and out.exists()
        check(ok, f"render.py 产出真实成片：exit={pr.returncode} exists={out.exists()}")
        if ok:
            json_part = pr.stdout[: pr.stdout.rindex("}") + 1]
            probe = json.loads(json_part)["probe"]
            check(probe["video"]["width"] == 1080 and probe["video"]["height"] == 1920,
                  f"成片画幅 {probe['video']['width']}x{probe['video']['height']}")
            check("QC PASS" in pr.stdout, "render 后自动 QC PASS")

        pb = subprocess.run([sys.executable, str(RENDER), "--inputs", str(a), "--out", str(tdp / "b.mp4"),
                             "--bgm", str(a)], capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        check(pb.returncode == 2 and "BLOCKED" in pb.stdout,
              f"未登记 BGM 被拒绝：exit={pb.returncode} {(pb.stdout or '').strip()[:60]}")

    # ---- 7. 真实库完整性（只读） ----
    c = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    check(c.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "真实库 integrity_check=ok")
    check(c.execute("SELECT COUNT(*) FROM entries").fetchone()[0] >= 103, "真实库条目未减少")
    c.close()

    print()
    if failures:
        print(f"FAILED {len(failures)}:")
        for f in failures:
            print("  -", f)
        return 2
    print("PASS test_remediation: 规则/同步/FTS/时间/标签/来源/关联/状态机/只读status/四周期/渲染/BGM闸门 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
