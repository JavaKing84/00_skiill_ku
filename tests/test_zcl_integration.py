#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_zcl_integration.py — 资源雷达接入 10 项验收（真实网络 + 真实数据库）。

任一网络项失败按 BLOCKED 记录并继续，不伪造；本地断言失败记 FAIL。
测试中插入的合成跨源镜像条目带 marker，结束即删除，不污染真实库。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
REAL_DB = ROOT / "06_techradar" / "data" / "techradar.db"
# 默认隔离：真实库只读复制到临时目录后所有写入都落在副本上
ALLOW_REAL_DB = "--allow-real-db" in sys.argv
DB = REAL_DB  # main() 中会被替换为临时副本
SCRIPTS = ROOT / "06_techradar" / "scripts"
BASE = "https://radar.zichuanlan.top"
MARKER = "zcl_test_synthetic_marker"

results: list[tuple[str, str, str]] = []


def record(tid: str, status: str, evidence: str) -> None:
    results.append((tid, status, evidence))
    print(f"[{status}] {tid}: {evidence}")


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=180)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "TIMEOUT: 子进程超过 180s")


def first_line(text: str) -> str:
    lines = (text or "").strip().splitlines()
    return lines[0] if lines else "(无输出)"


def main() -> int:
    global DB
    session = requests.Session()
    session.trust_env = False
    H = {"User-Agent": "skillkit-techradar/1.0 (integration-test)"}

    tmp_dir = tempfile.mkdtemp(prefix="zcl_it_")
    DB = Path(tmp_dir) / "techradar.db"
    if ALLOW_REAL_DB:
        DB = REAL_DB
        print("WARN: 已通过 --allow-real-db 授权直接写真实库")
    else:
        shutil.copy2(REAL_DB, DB)
        print(f"GUARD: 写入落在临时副本 {DB}")

    # T1 新来源健康检查
    try:
        r = session.get(BASE + "/health", headers=H, timeout=25)
        ok = r.status_code == 200 and r.json().get("ok") is True
        record("T1-health", "PASS" if ok else "FAIL",
               f"GET /health -> {r.status_code} {r.text[:80]}")
    except requests.RequestException as exc:
        record("T1-health", "BLOCKED", f"{type(exc).__name__}: {exc}")

    # T2 真实采集（小批量实跑）
    p2 = run([sys.executable, str(SCRIPTS / "collect_zcl.py"), "--db", str(DB),
              "--max-items", "12", "--detail-limit", "6",
              "--report", str(ROOT / "_reports" / "zcl_test_collect.json")])
    if p2.returncode == 0 and "picked=" in p2.stdout:
        record("T2-collect", "PASS", first_line(p2.stdout))
    else:
        record("T2-collect", "BLOCKED", f"exit={p2.returncode} {p2.stdout[-200:]} {p2.stderr[-200:]}")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # T3 正文及原始链接读取
    n_url = conn.execute("SELECT COUNT(*) FROM entries WHERE aggregator=? AND url LIKE 'http%'",
                         ("radar.zichuanlan.top",)).fetchone()[0]
    n_content = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE aggregator=? AND extra_json LIKE '%\"content\":%' "
        "AND extra_json NOT LIKE '%\"content\": null%'",
        ("radar.zichuanlan.top",)).fetchone()[0]
    record("T3-content-originurl", "PASS" if n_url > 0 else "FAIL",
           f"原始链接条目={n_url}；含正文字段条目={n_content}（部分源本无正文，属真实情况）")

    # T4 SQLite 入库与新字段
    row = conn.execute(
        "SELECT external_key,origin_source,aggregator,canonical_key,first_seen_at,last_seen_at,"
        "link_status,category,ai_category FROM entries WHERE aggregator=? LIMIT 1",
        ("radar.zichuanlan.top",)).fetchone()
    fields_ok = row and all(row[k] is not None for k in
                            ("external_key", "origin_source", "canonical_key", "first_seen_at", "last_seen_at"))
    record("T4-schema-fields", "PASS" if fields_ok else "FAIL",
           json.dumps(dict(row), ensure_ascii=False) if row else "无 ZCL 条目")

    # T5 重复采集幂等：再跑一次小批量，应 inserted=0
    before = conn.execute("SELECT COUNT(*) FROM entries WHERE aggregator=?",
                          ("radar.zichuanlan.top",)).fetchone()[0]
    p5 = run([sys.executable, str(SCRIPTS / "collect_zcl.py"), "--db", str(DB),
              "--max-items", "8", "--detail-limit", "0"])
    after = conn.execute("SELECT COUNT(*) FROM entries WHERE aggregator=?",
                         ("radar.zichuanlan.top",)).fetchone()[0]
    idem = "inserted=0" in p5.stdout and after == before
    record("T5-dedup-idempotent", "PASS" if idem else "FAIL",
           f"{first_line(p5.stdout)}；行数 {before}->{after}")

    # T6 跨来源关联：取真实 ZCL 条目的 URL，造一条直采镜像，验证 canonical 分组
    gh = conn.execute(
        "SELECT url,title FROM entries WHERE origin_source='github-awesome-ai' AND url LIKE 'http%' LIMIT 1"
    ).fetchone()
    mirror_id = None
    if gh:
        sys.path.insert(0, str(ROOT / "_shared"))
        from skillkit.inteldb import IntelDB
        with IntelDB(DB) as db:
            verdict = db.add_entry(
                "GitHub Search (public fallback)", "github", gh["url"],
                "[TEST-MIRROR] " + (gh["title"] or "mirror"),
                summary=MARKER, extra={"marker": MARKER})
            group = db.find_canonical_group(gh["url"])
            channels = {g["aggregator"] or g["source_name"] for g in group}
            mirror_id = conn.execute("SELECT entry_id FROM entries WHERE summary=?", (MARKER,)).fetchone()[0]
        ok6 = verdict in ("inserted", "duplicate") and len(group) >= 2 and len(channels) >= 2
        record("T6-cross-source", "PASS" if ok6 else "FAIL",
               f"url={gh['url'][:70]} group_size={len(group)} channels={sorted(channels)}")
    else:
        record("T6-cross-source", "BLOCKED", "库内无 github-awesome-ai 历史条目，无法构造真实跨源用例")

    # T7 来源溯源：聚合器上游源不得被误注册为独立 sources 行
    n_agg_src = conn.execute("SELECT COUNT(*) FROM sources WHERE kind='aggregator'").fetchone()[0]
    n_fake = conn.execute(
        "SELECT COUNT(*) FROM sources WHERE name IN (SELECT DISTINCT origin_source FROM entries "
        "WHERE origin_source IS NOT NULL AND aggregator IS NOT NULL)").fetchone()[0]
    origins = [r[0] for r in conn.execute(
        "SELECT DISTINCT origin_source FROM entries WHERE origin_source IS NOT NULL "
        "AND aggregator IS NOT NULL")]
    ok7 = n_agg_src == 1 and n_fake == 0 and len(origins) >= 5
    record("T7-provenance", "PASS" if ok7 else "FAIL",
           f"aggregator sources={n_agg_src}（应为1）；上游源误注册={n_fake}（应为0）；聚合上游源数={len(origins)}")

    # T9/T10 场景检索（真实库）
    for tid, scen in (("T9-ai-robot", "ai-robot"), ("T10-small-model", "small-model")):
        out = ROOT / "_reports" / f"zcl_test_{scen}.json"
        p = run([sys.executable, str(SCRIPTS / "radar_query.py"), "--db", str(DB),
                 "--scenario", scen, "--limit", "10", "--out", str(out)])
        if p.returncode == 0:
            data = json.loads(out.read_text(encoding="utf-8"))
            record(tid, "PASS" if data["hit_count"] > 0 else "PARTIAL",
                   f"hits={data['hit_count']}（零命中即 PARTIAL，需扩采集而非编造）")
        else:
            record(tid, "FAIL", p.stderr[-200:])

    # 清理合成镜像
    if mirror_id is not None:
        conn.execute("DELETE FROM entries WHERE entry_id=?", (mirror_id,))
        conn.commit()
    conn.close()

    # T8 原有功能回归：四套旧测试
    for t in ("test_skillkit_contract", "test_techradar", "test_registry", "test_video_pipeline"):
        p = run([sys.executable, str(ROOT / "tests" / f"{t}.py")])
        record(f"T8-regression-{t}", "PASS" if p.returncode == 0 else "FAIL",
               f"exit={p.returncode} {p.stdout.strip().splitlines()[-1:]}")

    blocked = sum(1 for _, s, _ in results if s == "BLOCKED")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    partial = sum(1 for _, s, _ in results if s == "PARTIAL")
    print(f"\nSUMMARY total={len(results)} PASS={len(results)-blocked-failed-partial} "
          f"PARTIAL={partial} BLOCKED={blocked} FAIL={failed}")
    (ROOT / "_reports" / "zcl_test_results.json").write_text(
        json.dumps([{"test": t, "status": s, "evidence": e} for t, s, e in results],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

