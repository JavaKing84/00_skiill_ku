#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lifecycle_run.py — TechRadar 生命周期任务执行器（daily / weekly / monthly / quarterly）。

安全默认：
  - 不带 --apply 时全部为 dry-run：只输出预计清理数量与空间，不删除任何行。
  - 即使带 --apply，若 lifecycle_config.json 的 apply_purge=false，仍强制 dry-run。
  - 真实删除前必然先做数据库备份，并把整行 JSON 写入 purge_log（可 restore）。
定时任务调用本脚本；也可人工执行。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))

from skillkit import lifecycle as lc  # noqa: E402
from skillkit.inteldb import IntelDB  # noqa: E402

DB_DEFAULT = ROOT / "06_techradar" / "data" / "techradar.db"
CFG_DEFAULT = ROOT / "06_techradar" / "data" / "lifecycle_config.json"
REPORT_DIR = ROOT / "_reports" / "lifecycle"
BACKUP_DIR = ROOT / "_backup" / "lifecycle"
SCRIPTS = ROOT / "06_techradar" / "scripts"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backup_db(db_path: Path, job: str, ts: str) -> Path:
    """用 SQLite 在线备份 API，保证一致性；随后写 SHA256 清单。"""
    dest_dir = BACKUP_DIR / f"{ts}_{job}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "techradar.db"
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(dest))
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    manifest = dest_dir / "manifest.json"
    manifest.write_text(json.dumps({
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "job": job, "source": str(db_path), "backup": str(dest),
        "bytes": dest.stat().st_size, "sha256": sha256_file(dest),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def run_collectors() -> dict:
    """每日采集：通道 A（公开，零凭证）+ 通道 B（Folo / Reddit，认证）。

    采集是增量写入，不属于删除，dry-run 下照常执行。
    退出码 3 = 该认证源缺少凭据/待审批（BLOCKED，不算采集失败，不影响其它通道）。
    """
    result = {"steps": [], "failed": 0}
    commands = [
        ["collect_public_suite.py", "--db", str(DB_DEFAULT), "--limit", "20"],
        ["collect_folo.py", "--db", str(DB_DEFAULT), "--limit", "20"],
        ["collect_reddit.py", "--db", str(DB_DEFAULT), "--limit", "25"],
        # 排障型来源：技术板块 / GitHub Issues / Stack Overflow
        ["collect_reddit_topics.py", "--db", str(DB_DEFAULT), "--limit", "10"],
        ["collect_github_issues.py", "--db", str(DB_DEFAULT), "--limit", "6"],
        ["collect_stackoverflow.py", "--db", str(DB_DEFAULT), "--limit", "8"],
        # 采集只拿到标题+摘要（约 250 字），正文必须回源抓；每轮补 30 条，长尾由后续轮次补齐
        ["fetch_bodies.py", "--db", str(DB_DEFAULT), "--category", "security", "--limit", "30"],
        # 全分类正文补抓（RSS 不能只当目录用）：opensource/news/research 等每轮 15 条
        ["fetch_bodies.py", "--db", str(DB_DEFAULT), "--category", "", "--limit", "15"],
        # 特征标签（anti-bot / troubleshooting / code-snippet / windows-permission）
        ["tagging.py", "--db", str(DB_DEFAULT), "--hours", "3"],
    ]
    for cmd in commands:
        script = SCRIPTS / cmd[0]
        if not script.exists():
            result["steps"].append({"collector": cmd[0], "status": "missing"})
            result["failed"] += 1
            continue
        p = subprocess.run([sys.executable, str(script), *cmd[1:]], capture_output=True,
                           text=True, cwd=str(ROOT), timeout=1800)
        # stdout 全文保留（解析 SUMMARY 用），展示字段只留首行；此前只留首行导致
        # collect_public_suite 的 SUMMARY 行（在表格后面）永远被丢弃 → collected 恒 0。
        full = p.stdout or ""
        line = (full.strip().splitlines() or [""])[0]
        entry = {"collector": cmd[0], "exit": p.returncode, "stdout": line[:300],
                 "stdout_full": full[-4000:]}
        if p.returncode == 3:
            entry["status"] = "BLOCKED"
        elif p.returncode != 0:
            entry["status"] = "FAILED"
            result["failed"] += 1
        else:
            entry["status"] = "OK"
        result["steps"].append(entry)
    return result


def parse_counts(steps: list[dict]) -> dict:
    """从采集器输出解析 collected/inserted/deduped。

    优先读取机器可读的 `SUMMARY collected=.. inserted=.. deduped=.. failed=..` 行；
    兼容旧采集器的 `fetched=/picked=/inserted=/duplicate=/updated=` 形式。
    注意：SUMMARY 可能在 stdout 任意位置（表格之后），必须扫描全文——
    只看首行会把 collect_public_suite 的表头当成唯一输出，统计恒 0。
    """
    out = {"collected": 0, "inserted": 0, "deduped": 0}
    for s in steps:
        text = s.get("stdout_full") or s.get("stdout", "")
        if "SUMMARY " in text:
            for token in text.split("SUMMARY ", 1)[1].replace(",", " ").split():
                if "=" not in token:
                    continue
                k, v = token.split("=", 1)
                if not v.isdigit():
                    continue
                if k == "collected":
                    out["collected"] += int(v)
                elif k == "inserted":
                    out["inserted"] += int(v)
                elif k == "deduped":
                    out["deduped"] += int(v)
            continue
        for token in text.replace(",", " ").split():
            if "=" not in token:
                continue
            k, v = token.split("=", 1)
            if not v.isdigit():
                continue
            if k in ("fetched", "picked"):
                out["collected"] += int(v)
            elif k == "inserted":
                out["inserted"] += int(v)
            elif k in ("duplicate", "deduped", "updated"):
                out["deduped"] += int(v)
    return out


def job_daily(conn: sqlite3.Connection, cfg: dict, args) -> dict:
    detail = {"steps": []}
    if not args.no_collect:
        collected = run_collectors()
        detail["collect"] = collected
        counts = parse_counts(collected["steps"])
        detail.update(counts)
        detail["failed"] = collected["failed"]
    else:
        detail["collect"] = {"skipped": "--no-collect"}
    refreshed = lc.refresh_link_status(conn)
    detail["link_status_updated"] = refreshed
    scored = lc.rescore_all(conn, cfg)
    detail["rescore"] = scored
    added = lc.capture_snapshots(conn) if not args.dry_run else 0
    detail["snapshots_added"] = added
    detail["status"] = "PASS" if detail.get("failed", 0) == 0 else "PARTIAL"
    return detail


def job_weekly(conn: sqlite3.Connection, cfg: dict, args, apply: bool) -> dict:
    detail = {"steps": []}
    health_out = ROOT / "_reports" / f"health_{datetime.now():%Y%m%d_%H%M%S}.json"
    try:
        p = subprocess.run([sys.executable, str(SCRIPTS / "healthcheck.py"), "--out", str(health_out)],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=180)
        detail["health"] = (p.stdout.strip().splitlines() or [""])[0]
        detail["health_exit"] = p.returncode
    except (subprocess.SubprocessError, OSError) as exc:
        detail["health"] = f"BLOCKED: {type(exc).__name__}"
    refreshed = lc.refresh_link_status(conn)
    detail["link_status_updated"] = refreshed
    detail["duplicates"] = lc.duplicate_report(conn)[:10]
    plan = lc.plan_purge(conn, cfg)
    detail["purge_plan"] = {
        "candidates": len(plan),
        "estimated_bytes": sum(c.bytes for c in plan),
        "by_tier": {t: sum(1 for c in plan if c.tier == t) for t in ("P0", "P1", "P2", "P3")},
        "by_reason": {},
        "top": [{"entry_id": c.entry_id, "title": (c.title or "")[:40], "tier": c.tier,
                 "score": c.score, "reason": c.reason, "age_days": c.age_days} for c in plan[:15]],
    }
    for c in plan:
        detail["purge_plan"]["by_reason"][c.reason] = detail["purge_plan"]["by_reason"].get(c.reason, 0) + 1
    if apply and plan:
        backup = backup_db(DB_DEFAULT, "weekly", datetime.now().strftime("%Y%m%d_%H%M%S"))
        detail["backup"] = str(backup)
        res = lc.apply_purge(conn, plan, run_id=args.run_id, batch_limit=500)
        detail["purged"] = res["deleted"]
        detail["bytes_freed"] = res["bytes"]
    else:
        detail["purged"] = 0
        detail["dry_run_note"] = "未删除；plan 为预计清理量"
    detail["status"] = "PASS"
    return detail


def job_monthly(conn: sqlite3.Connection, cfg: dict, args, apply: bool) -> dict:
    detail = {"steps": []}
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = backup_db(DB_DEFAULT, "monthly", ts)
    detail["backup"] = {"path": str(backup), "sha256": sha256_file(backup),
                        "bytes": backup.stat().st_size}
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    quick = conn.execute("PRAGMA quick_check").fetchone()[0]
    detail["integrity"] = {"integrity_check": integrity, "quick_check": quick}
    detail["rescore"] = lc.rescore_all(conn, cfg)
    down = lc.downsample_snapshots(conn, cfg, run_id=args.run_id, dry_run=not apply)
    detail["snapshots"] = down
    plan = lc.plan_purge(conn, cfg)
    detail["purge_plan"] = {
        "candidates": len(plan), "estimated_bytes": sum(c.bytes for c in plan),
        "by_tier": {t: sum(1 for c in plan if c.tier == t) for t in ("P0", "P1", "P2", "P3")},
    }
    if apply and plan:
        res = lc.apply_purge(conn, plan, run_id=args.run_id)
        detail["purged"] = res["deleted"]
        detail["bytes_freed"] = res["bytes"] + down.get("bytes", 0)
        try:
            conn.execute("VACUUM")
            detail["vacuum"] = "done"
        except sqlite3.Error as exc:
            detail["vacuum"] = f"skipped: {exc}"
    else:
        detail["purged"] = 0
    detail["tables"] = lc.table_stats(conn)
    ok = integrity == "ok" and quick == "ok"
    detail["status"] = "PASS" if ok else "FAIL"
    return detail


def job_quarterly(conn: sqlite3.Connection, cfg: dict, args) -> dict:
    detail = {"steps": []}
    sources = [{"name": r[0], "kind": r[1], "auth_state": r[2]} for r in conn.execute(
        "SELECT name, kind, auth_state FROM sources ORDER BY kind, name")]
    tiers = {r[0] or "NULL": r[1] for r in conn.execute(
        "SELECT value_tier, COUNT(*) FROM entries GROUP BY value_tier")}
    cats = [{"category": r[0], "n": r[1]} for r in conn.execute(
        "SELECT COALESCE(category,'NULL'), COUNT(*) FROM entries GROUP BY category ORDER BY 2 DESC")]
    growth = {
        "last_7d": conn.execute(
            "SELECT COUNT(*) FROM entries WHERE first_seen_at >= date('now','-7 day')").fetchone()[0],
        "last_30d": conn.execute(
            "SELECT COUNT(*) FROM entries WHERE first_seen_at >= date('now','-30 day')").fetchone()[0],
    }
    policy = [{"key": r[0], "scope": r[1], "selector": r[2], "days": r[3], "action": r[4]}
              for r in conn.execute("SELECT policy_key,scope,selector,retain_days,action "
                                    "FROM retention_policy ORDER BY policy_key")]
    schema = [{"table": r[0], "sql": (r[1] or "")[:160]} for r in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    detail.update({
        "skill_version": cfg.get("skill_version"),
        "sources": sources, "tiers": tiers, "categories": cats[:15], "growth": growth,
        "retention_policy": policy, "schema_summary": schema,
        "db_bytes": DB_DEFAULT.stat().st_size,
        "recommendations": _quarterly_recommendations(conn, cfg),
        "status": "PASS",
    })
    return detail


def _quarterly_recommendations(conn: sqlite3.Connection, cfg: dict) -> list[str]:
    recs = []
    n_entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    n_null_tier = conn.execute("SELECT COUNT(*) FROM entries WHERE value_tier IS NULL").fetchone()[0]
    if n_null_tier:
        recs.append(f"{n_null_tier} 条尚未评分，建议执行 monthly 重新评分")
    if n_entries == 0:
        recs.append("库为空，请先运行 daily 采集")
    blocked = conn.execute("SELECT COUNT(*) FROM sources WHERE auth_state='auth_required'").fetchone()[0]
    if blocked:
        recs.append(f"{blocked} 个来源处于 auth_required，需用户补凭据")
    dup = lc.duplicate_report(conn)
    if dup:
        recs.append(f"{len(dup)} 组潜在重复（canonical_key 相同但内容哈希不同），建议人工合并")
    stale = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE last_seen_at < date('now','-180 day')").fetchone()[0]
    if stale:
        recs.append(f"{stale} 条超过 180 天未被再次观测，可在 confirm 后按策略清理")
    return recs or ["无异常，维持当前策略"]


def render_md(job: str, detail: dict, cfg: dict, run: dict) -> str:
    lines = [
        f"# 生命周期任务报告 · {job}",
        "",
        f"- 运行 ID：{run['run_id']}",
        f"- 模式：**{'DRY-RUN（未删除）' if run['mode'] == 'dry-run' else 'APPLY（已按策略执行）'}**",
        f"- 开始 / 结束：{run['started_at']} / {run.get('finished_at')}",
        f"- 状态：**{detail.get('status', 'PASS')}**",
        f"- Skill 版本：{cfg.get('skill_version')}　配置 apply_purge={cfg.get('apply_purge')}",
        "",
        "## 计数",
        f"- 采集：{detail.get('collected', 0)}　入库：{detail.get('inserted', 0)}　"
        f"去重/更新：{detail.get('deduped', 0)}　失败：{detail.get('failed', 0)}",
        f"- 清理：{detail.get('purged', 0)} 条　释放：{detail.get('bytes_freed', 0)} 字节",
        "",
    ]
    plan = detail.get("purge_plan")
    if plan:
        lines += [
            "## 清理计划（预计）",
            f"- 候选：{plan['candidates']} 条　预计空间：{plan['estimated_bytes']} 字节",
            f"- 分档：{plan.get('by_tier')}",
            "",
            "| entry_id | 档位 | 分数 | 年龄(天) | 原因 | 标题 |",
            "|---|---|---|---|---|---|",
        ]
        for t in plan.get("top", []):
            lines.append(f"| {t['entry_id']} | {t['tier']} | {t['score']} | {t['age_days']} | "
                         f"{t['reason']} | {(t['title'] or '')[:36]} |")
        lines.append("")
    if detail.get("integrity"):
        lines += ["## 完整性检查", f"- {detail['integrity']}", ""]
    if detail.get("backup"):
        lines += ["## 备份", f"- {detail['backup']}", ""]
    lines += ["## 明细（JSON）", "```json",
              json.dumps(detail, ensure_ascii=False, indent=2)[:6000], "```", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True, choices=["daily", "weekly", "monthly", "quarterly"])
    ap.add_argument("--db", default=str(DB_DEFAULT))
    ap.add_argument("--config", default=str(CFG_DEFAULT))
    ap.add_argument("--apply", action="store_true", help="允许真实删除（仍需 config.apply_purge=true）")
    ap.add_argument("--no-collect", action="store_true", help="daily 跳过网络采集")
    ap.add_argument("--report-dir", default=str(REPORT_DIR))
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"FAIL: database not found {db_path}")
        return 2
    cfg_path = Path(args.config)
    cfg = lc.load_config(cfg_path)
    lc.save_config(cfg_path, cfg)          # 首次运行落盘默认配置，便于人工改
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    apply = bool(args.apply and cfg.get("apply_purge"))
    if args.apply and not cfg.get("apply_purge"):
        print("NOTICE: --apply 被配置 apply_purge=false 拦截，本次仍为 dry-run")
    mode = "apply" if apply else "dry-run"

    db = IntelDB(db_path)
    conn = db.conn
    reaped = lc.reap_stale_runs(conn, minutes=30)
    if reaped:
        print(f"NOTICE: 回收 {reaped} 条中断的 running 记录（标记 FAIL）")
    started = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute("INSERT INTO job_runs(job_name,mode,started_at,status) VALUES(?,?,?,'running')",
                       (args.job, mode, started))
    run_id = int(cur.lastrowid)
    conn.commit()
    args.run_id = run_id
    args.dry_run = not apply

    lc.sync_policy_table(conn, cfg)

    detail: dict = {}
    status = "FAIL"
    try:
        if args.job == "daily":
            detail = job_daily(conn, cfg, args)
        elif args.job == "weekly":
            detail = job_weekly(conn, cfg, args, apply)
        elif args.job == "monthly":
            detail = job_monthly(conn, cfg, args, apply)
        else:
            detail = job_quarterly(conn, cfg, args)
        status = detail.get("status", "PASS")
    except Exception as exc:  # 记录失败，不吞掉
        detail = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        status = "FAIL"
    finished = datetime.now().isoformat(timespec="seconds")

    run = {
        "run_id": run_id, "job_name": args.job, "mode": mode,
        "started_at": started, "finished_at": finished,
        "collected": detail.get("collected", 0), "inserted": detail.get("inserted", 0),
        "deduped": detail.get("deduped", 0), "failed": detail.get("failed", 0),
        "purged": detail.get("purged", 0), "bytes_freed": detail.get("bytes_freed", 0),
        "status": status,
    }
    conn.execute(
        "UPDATE job_runs SET finished_at=?, collected=?, inserted=?, deduped=?, failed=?, "
        "purged=?, bytes_freed=?, status=?, detail_json=? WHERE run_id=?",
        (finished, run["collected"], run["inserted"], run["deduped"], run["failed"],
         run["purged"], run["bytes_freed"], status,
         json.dumps(detail, ensure_ascii=False)[:200000], run_id),
    )
    conn.commit()

    out_dir = Path(args.report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{args.job}_{ts}.md"
    json_path = out_dir / f"{args.job}_{ts}.json"
    md_path.write_text(render_md(args.job, detail, cfg, run), encoding="utf-8")
    json_path.write_text(json.dumps({"run": run, "detail": detail}, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    db.close()

    print(f"{args.job} mode={mode} status={status} run_id={run_id} "
          f"purged={run['purged']} bytes={run['bytes_freed']}")
    print(f"-> {md_path}")
    return 0 if status in ("PASS", "PARTIAL") else 2


if __name__ == "__main__":
    raise SystemExit(main())
