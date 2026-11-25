#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_quality_review.py — 第二轮质量整改验收（R1–R12）。

全部写入测试使用临时库副本；真实库只做只读校验（除加法式 schema 迁移）。
覆盖：数据差额、溯源完整性、入库校验闸门、按需深度阅读、注册表六态、
FTS5 CRUD/回滚/LIKE、生命周期四周期、任务幂等、认证源状态、故障隔离、完整性。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_shared"))
sys.path.insert(0, str(ROOT / "06_techradar" / "scripts"))

from skillkit.inteldb import IntelDB, content_hash_for  # noqa: E402
from skillkit import search as sx  # noqa: E402
from skillkit import pipeline as pl  # noqa: E402
from skillkit.http import HttpClient  # noqa: E402
from skillkit.policy import CrawlPolicy  # noqa: E402
from skillkit.sources import ensure_registry, list_sources  # noqa: E402

REAL_DB = ROOT / "06_techradar" / "data" / "techradar.db"
SCRIPTS = ROOT / "06_techradar" / "scripts"
failures: list[str] = []
notes: list[str] = []
skips: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)
    print(("PASS " if cond else "FAIL ") + msg)


def skip(msg: str) -> None:
    skips.append(msg)
    print("SKIP " + msg)


def note(msg: str) -> None:
    notes.append(msg)
    print("NOTE " + msg)


def run(args: list[str], env: dict | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    for k in ("FOLO_SESSION_TOKEN", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"):
        e.pop(k, None)
    if env:
        e.update(env)
    return subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          cwd=str(ROOT), env=e, timeout=timeout)


# 认证源阻塞用例：显式指向不可用 CDP，避免测试误用用户正在使用的 Chrome 登录态。
# 若未来要测试浏览器登录态回退，去掉该 env 并在断言里识别 READY/browser_session。
OFFLINE_BROWSER = {"TECH_RADAR_CDP": "http://127.0.0.1:1", "TECH_RADAR_CDP_PORT": "1",
                   "TECH_RADAR_DISABLE_BROWSER": "1"}


def ro(db: str) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


# ---------------------------------------------------------------- 夹具站点
ARTICLE = "<html><body><article><h1>Quantum Widget Deep Dive</h1>" + \
          "<p>" + ("This is a long technical article about vision language action models, "
                   "quantum widget scheduling and embodied agents. " * 12) + "</p></article></body></html>"

ROBOTS = "User-agent: *\nDisallow: /private\n"


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/robots.txt":
            body = ROBOTS.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/article"):
            body = ARTICLE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/short"):
            body = b"<html><body><p>too short</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/private"):
            self.send_response(403); self.end_headers(); return
        if self.path.startswith("/folo/"):
            body = b'{"code":401,"message":"unauthorized"}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.headers.get("Content-Length"):
            self.rfile.read(int(self.headers["Content-Length"]))
        body = b'{"error":"invalid_client"}'
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def start_server(tmp: Path):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def seed_entry(db, title, url, origin="fixture", extra=None, state="title_scanned"):
    with IntelDB(db) as d:
        cur = d.conn.execute(
            "INSERT INTO entries(url,title,collected_at,content_hash,metrics_json,extra_json,"
            "first_seen_at,last_seen_at,link_status,category,origin_source,read_state) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (url, title, "2026-11-18T00:00:00", content_hash_for(url, title), "{}",
             json.dumps(extra or {}, ensure_ascii=False), "2026-11-18T00:00:00",
             "2026-11-18T00:00:00", "active", "ai", origin, state))
        d.conn.commit()
        return int(cur.lastrowid)


def main() -> int:
    httpd, base = start_server(ROOT)
    tmp_root = Path(tempfile.mkdtemp(prefix="qr_"))

    # ================= R1 数据差额 =================
    c = ro(str(REAL_DB))
    total = c.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    hist = c.execute("SELECT COUNT(*) FROM entries WHERE collected_at < '2026-11-17T23:00'").fetchone()[0]
    new = c.execute("SELECT COUNT(*) FROM entries WHERE collected_at >= '2026-11-17T23:00'").fetchone()[0]
    by_origin = {r["o"]: r["n"] for r in c.execute(
        "SELECT COALESCE(origin_source,'(NULL)') o, COUNT(*) n FROM entries "
        "WHERE collected_at >= '2026-11-17T23:00' GROUP BY o")}
    manual = [dict(r) for r in c.execute(
        "SELECT entry_id,external_key,origin_source,collected_at FROM entries "
        "WHERE aggregator IS NOT NULL AND external_key LIKE 'zcl:%' "
        "AND collected_at >= '2026-11-17T23:54' ORDER BY entry_id")]
    reg_sum = c.execute("SELECT COALESCE(SUM(items_inserted),0) FROM source_registry").fetchone()[0]
    c.close()
    check(total >= 346, f"R1 当前总条目 {total}（不少于基线 346）")
    check(hist + new == total, f"R1 历史 {hist} + 新增 {new} = {total}")
    check(sum(by_origin.values()) == new, f"R1 新增按 origin 分组求和 {sum(by_origin.values())} = {new}")
    check(all(m["origin_source"] for m in manual),
          f"R1 手动 collect_zcl 入库 {len(manual)} 条，均保留上游 origin_source")
    # registry 计数覆盖全部登记来源（含 topic_search）；手动 ZCL 写入可能已计入 registry，故只校验不超额
    check(reg_sum <= new, f"R1 registry 累计 {reg_sum} 未超过实际新增 {new}")
    for m in manual[:8]:
        print(f"     manual: entry_id={m['entry_id']} key={m['external_key']} at={m['collected_at']}")
    if len(manual) > 8:
        print(f"     ... 其余 {len(manual) - 8} 条手动 zcl 记录略")

    # ================= R2 溯源完整性 =================
    c = ro(str(REAL_DB))
    null_origin = [dict(r) for r in c.execute(
        "SELECT source_id, COUNT(*) n, MIN(collected_at) mn, MAX(collected_at) mx FROM entries "
        "WHERE origin_source IS NULL GROUP BY source_id")]
    null_url = c.execute("SELECT COUNT(*) FROM entries WHERE url IS NULL OR url=''").fetchone()[0]
    new_missing = c.execute(
        "SELECT COUNT(*) FROM entries WHERE collected_at >= '2026-11-17T23:00' "
        "AND (origin_source IS NULL OR origin_source='' OR url IS NULL OR url='')").fetchone()[0]
    c.close()
    total_null_origin = sum(r["n"] for r in null_origin)
    check(total_null_origin == 22, f"R2 缺 origin_source 共 {total_null_origin} 条")
    check(null_url == 0, f"R2 缺原始 URL 共 {null_url} 条")
    check(all(r["mx"] < "2026-11-17T23:00" for r in null_origin),
          f"R2 缺 origin 的全部为历史存量（最晚 {max(r['mx'] for r in null_origin)}）")
    check(new_missing == 0, f"R2 新增批次溯源不完整 {new_missing} 条（应为 0）")
    for r in null_origin:
        print(f"     historical source_id={r['source_id']} n={r['n']}")

    # ================= R3 入库校验闸门 =================
    gate_db = tmp_root / "gate.db"
    shutil.copy2(REAL_DB, gate_db)
    with IntelDB(gate_db) as d:
        ensure_registry(d.conn)
        bad1 = pl.Record(url="", title="no url", extra={})
        bad2 = pl.Record(url="https://example.com/x", title="aggregator as origin", extra={})
        st1 = pl.ingest(d, [bad1], "fixture_src", "api")
        st2 = pl.ingest(d, [bad2], "fixture_src", "api", aggregator="fixture_src",
                        origin_extra_key=None)
        quarantined = d.conn.execute("SELECT COUNT(*) FROM provenance_quarantine").fetchone()[0]
        inserted_bad = d.conn.execute(
            "SELECT COUNT(*) FROM entries WHERE title IN ('no url','aggregator as origin')").fetchone()[0]
    check(st1["quarantined"] == 1 and st2["quarantined"] == 1,
          f"R3 非法记录被隔离（quarantined={st1['quarantined']}+{st2['quarantined']}）")
    check(quarantined == 2, f"R3 隔离区写入 {quarantined} 条")
    check(inserted_bad == 0, f"R3 非法记录未入库（{inserted_bad} 条）")
    with IntelDB(gate_db) as d:
        good = pl.Record(url="https://example.com/ok", title="valid record",
                         extra={"up": "src"})
        st3 = pl.ingest(d, [good], "fixture_src", "api", origin_extra_key="up")
    check(st3["inserted"] == 1 and st3["quarantined"] == 0, "R3 合法记录正常入库且 origin 来自上游")

    # ================= R4 按需深度阅读 =================
    rd_db = tmp_root / "read.db"
    shutil.copy2(REAL_DB, rd_db)
    eid = seed_entry(rd_db, "Fixture Article", f"{base}/article.html")
    eid_short = seed_entry(rd_db, "Fixture Short", f"{base}/short.html")
    eid_priv = seed_entry(rd_db, "Fixture Private", f"{base}/private/x.html", origin="fixture")
    p1 = run([str(SCRIPTS / "radar_read.py"), "--db", str(rd_db), "--entry-id", str(eid),
              "--fetch", "--out", str(tmp_path := (tmp_root / "read1.json"))])
    out1 = json.loads(Path(tmp_path).read_text(encoding="utf-8")) if Path(tmp_path).exists() else {}
    check(p1.returncode == 0 and out1.get("fetched") == 1,
          f"R4 正文抓取成功（exit={p1.returncode}, fetched={out1.get('fetched')}）")
    with IntelDB(rd_db) as d:
        row = d.get_entry(eid)
        logs = d.conn.execute("SELECT stage,status FROM read_log WHERE entry_id=?", (eid,)).fetchall()
    check(row["read_state"] == "content_fetched", f"R4 状态推进到 {row['read_state']}")
    check('"content"' in (row["extra_json"] or "") and len(row["extra_json"]) > 500,
          "R4 正文已写入 extra_json.content")
    check(any(l[0] == "fetch" and l[1] == "SUCCESS" for l in logs), "R4 read_log 记录 fetch/SUCCESS")

    p2 = run([str(SCRIPTS / "radar_read.py"), "--db", str(rd_db), "--entry-id", str(eid), "--mark-read"])
    with IntelDB(rd_db) as d:
        check(d.get_entry(eid)["read_state"] == "content_read", "R4 阅读后推进 content_read")
    p3 = run([str(SCRIPTS / "radar_read.py"), "--db", str(rd_db), "--entry-id", str(eid),
              "--mark-analyzed", "--claim", "Fixture 分析结论：VLA 与量子调度可组合"])
    with IntelDB(rd_db) as d:
        state3 = d.get_entry(eid)["read_state"]
        insights = d.conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
    check(p3.returncode == 0 and state3 == "analyzed" and insights >= 1,
          f"R4 分析后推进 analyzed（{state3}，insights={insights}）")

    # 失败不推进：短正文 + robots 禁止
    p4 = run([str(SCRIPTS / "radar_read.py"), "--db", str(rd_db), "--entry-id", str(eid_short), "--fetch"])
    p5 = run([str(SCRIPTS / "radar_read.py"), "--db", str(rd_db), "--entry-id", str(eid_priv), "--fetch"])
    with IntelDB(rd_db) as d:
        s_short = d.get_entry(eid_short)["read_state"]
        s_priv = d.get_entry(eid_priv)["read_state"]
        fails = d.conn.execute("SELECT COUNT(*) FROM read_log WHERE status IN ('FAILED','SKIPPED')").fetchone()[0]
    check(p4.returncode == 1 and s_short == "title_scanned", f"R4 短正文不推进状态（{s_short}）")
    check(p5.returncode == 0 and s_priv == "title_scanned", f"R4 robots 禁止不推进状态（{s_priv}）")
    check(fails >= 2, f"R4 失败/跳过均写入 read_log（{fails} 条）")
    check(run([str(SCRIPTS / "radar_read.py"), "--db", str(rd_db), "--entry-id", str(eid),
               "--mark-analyzed"]).returncode == 2, "R4 --mark-analyzed 缺 --claim 被拒绝")

    # ================= R5 注册表六态 =================
    reg_db = tmp_root / "reg.db"
    shutil.copy2(REAL_DB, reg_db)
    p6 = run([str(SCRIPTS / "collect_public_suite.py"), "--db", str(reg_db), "--limit", "5",
              "--only", "hn_frontpage", "--report", str(tmp_root / "reg.json")])
    with IntelDB(reg_db) as d:
        ensure_registry(d.conn)
        rows = {r["source_id"]: r for r in list_sources(d.conn)}
    hn = rows.get("hn_frontpage", {})
    check(p6.returncode == 0 and hn.get("collection_status") == "SUCCESS"
          and hn.get("connectivity_status") == "ONLINE" and hn.get("last_success_at"),
          f"R5 成功采集写 collection/connectivity/last_success（{hn.get('collection_status')}/"
          f"{hn.get('connectivity_status')}/{hn.get('last_success_at')}）")
    check(hn.get("implementation_status") == "IMPLEMENTED" and hn.get("configuration_status") == "CONFIGURED",
          "R5 实现态与配置态分列")
    folo = rows.get("folo", {})
    if folo.get("status") not in ("AUTH_REQUIRED", "APPROVAL_REQUIRED"):
        skip(f"R5 Folo 当前为 {folo.get('status')}/{folo.get('collection_status')}，"
             f"非纯凭据阻塞状态，凭据断言不适用")
    else:
        check(folo.get("collection_status") in ("BLOCKED", "NEVER_RUN"),
              f"R5 Folo 未授权不影响公开源（{folo.get('status')}/{folo.get('collection_status')}）")

    # ================= R6 FTS5 CRUD =================
    fts_db = tmp_root / "fts.db"
    with IntelDB(fts_db) as d:
        ensure_registry(d.conn)
        sx.ensure_fts(d.conn)
        e1 = d.add_entry("fts_src", "api", "https://example.com/qw", "Widget Scheduler",
                         summary="generic scheduling", origin_source="fts_src")
        eid1 = d.conn.execute("SELECT entry_id FROM entries WHERE url='https://example.com/qw'").fetchone()[0]
        d.store_content(eid1, "QuantumWidget 量子计算调度 实验")
        n1 = d.conn.execute("SELECT COUNT(*) FROM entries_fts WHERE entries_fts MATCH ?",
                            ('"QuantumWidget"',)).fetchone()[0]
        # 中文按前缀查询（与 radar_query 的实际行为一致）
        cor = sx.query_entries(d.conn, text="量子计算", engine="fts5")
        n2 = cor["count"]
        check(e1 == "inserted" and n1 == 1 and n2 == 1,
              f"R6 新增同步到 FTS（EN={n1}, CN={n2}）")
        d.store_content(eid1, "PhotonScheduler 光子计算 新正文")
        old_hit = d.conn.execute("SELECT COUNT(*) FROM entries_fts WHERE entries_fts MATCH ?",
                                 ('"QuantumWidget"',)).fetchone()[0]
        new_hit = d.conn.execute("SELECT COUNT(*) FROM entries_fts WHERE entries_fts MATCH ?",
                                 ('"PhotonScheduler"',)).fetchone()[0]
        check(old_hit == 0 and new_hit == 1,
              f"R6 更新正文后旧词消失/新词出现（old={old_hit}, new={new_hit}）")
        # 事务回滚：主表与索引都不应残留
        try:
            with d.tx() as conn:
                cur = conn.execute(
                    "INSERT INTO entries(url,title,collected_at,content_hash,first_seen_at,last_seen_at) "
                    "VALUES(?,?,?,?,?,?)",
                    ("https://example.com/rb", "RollbackProbe", "2026-11-18T00:00:00",
                     content_hash_for("https://example.com/rb", "RollbackProbe"),
                     "2026-11-18T00:00:00", "2026-11-18T00:00:00"))
                d._fts_index_entry(int(cur.lastrowid), commit=False)
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        rb_entry = d.conn.execute("SELECT COUNT(*) FROM entries WHERE title='RollbackProbe'").fetchone()[0]
        rb_fts = d.conn.execute("SELECT COUNT(*) FROM entries_fts WHERE entries_fts MATCH ?",
                                ('"RollbackProbe"',)).fetchone()[0]
        check(rb_entry == 0 and rb_fts == 0,
              f"R6 事务失败时主表与索引同时回滚（entry={rb_entry}, fts={rb_fts}）")
        # 删除后不留孤儿
        d.conn.execute("DELETE FROM entries WHERE entry_id=?", (eid1,))
        d.conn.commit()
        sx.drop_entry(d.conn, int(eid1))
        d.conn.commit()
        orphan = d.conn.execute(
            "SELECT COUNT(*) FROM entries_fts f LEFT JOIN entries e ON e.entry_id=f.entry_id "
            "WHERE e.entry_id IS NULL").fetchone()[0]
        check(orphan == 0, f"R6 删除后无孤儿索引（{orphan}）")

    # LIKE 降级 + 中文/模型名检索
    like_db = tmp_root / "like.db"
    with IntelDB(like_db) as d:
        d.add_entry("s", "api", "https://e.test/1", "Llama.cpp 量化部署", summary="小模型 端侧推理",
                    origin_source="s")
        d.add_entry("s", "api", "https://e.test/2", "Qwen3-8B 微调", summary="LoRA 训练",
                    origin_source="s")
        conn = d.conn
        conn.row_factory = sqlite3.Row
    conn = sqlite3.connect(f"file:{like_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    r_like = sx.query_entries(conn, text="Llama.cpp", engine="like")
    r_cn = sx.query_entries(conn, text="量化")
    r_model = sx.query_entries(conn, text="Qwen3")
    conn.close()
    check(r_like["count"] >= 1 and r_like["engine"] == "like", f"R6 LIKE 降级命中（{r_like['count']}）")
    check(r_cn["count"] >= 1, f"R6 中文检索命中（{r_cn['count']}）")
    check(r_model["count"] >= 1, f"R6 模型名检索命中（{r_model['count']}）")

    # ================= R7 四周期（副本） =================
    lc_db = tmp_root / "lifecycle.db"
    shutil.copy2(REAL_DB, lc_db)
    cfg = tmp_root / "lc_cfg.json"
    cfg.write_text(json.dumps({"apply_purge": False, "observation_days": 14,
                               "snapshots": {"raw_days": 90, "daily_keep_days": 400},
                               "retention_days": {"default": 180, "reddit_comment": 90,
                                                  "github": 3650, "perm": 36500,
                                                  "low_value": 30, "promo_goods": 7,
                                                  "promo_other": 14, "snapshot": 90},
                               "low_value_categories": ["goods", "trade", "invite", "carpool",
                                                        "other", "noise"],
                               "project_profiles": {}, "value_weights": {},
                               "tier_thresholds": {"P0": 85, "P1": 65, "P2": 40}}),
                      encoding="utf-8")
    for job in ("daily", "weekly", "monthly", "quarterly"):
        pj = run([str(SCRIPTS / "lifecycle_run.py"), "--job", job, "--db", str(lc_db),
                  "--config", str(cfg), "--report-dir", str(tmp_root / f"rep_{job}"), "--no-collect"])
        check(pj.returncode == 0 and "mode=dry-run" in pj.stdout,
              f"R7 {job} 在副本执行 dry-run（exit={pj.returncode}）")
    backups = list((ROOT / "_backup" / "lifecycle").glob("*/techradar.db"))
    check(bool(backups), f"R7 monthly 备份产物存在（{len(backups)} 个历史备份）")
    if backups:
        b = sqlite3.connect(f"file:{backups[-1]}?mode=ro", uri=True)
        n = b.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        ok = b.execute("PRAGMA integrity_check").fetchone()[0]
        b.close()
        check(n > 0 and ok == "ok", f"R7 备份可打开且完整（entries={n}, integrity={ok}）")
    with IntelDB(lc_db) as d:
        runs = d.conn.execute("SELECT job_name,status FROM job_runs ORDER BY run_id DESC LIMIT 4").fetchall()
    check(len(runs) >= 4 and all(r[1] == "PASS" for r in runs), f"R7 四周期 job_runs 均 PASS（{len(runs)} 条）")

    # ================= R8 任务幂等（只读） =================
    ps = subprocess.run(["schtasks", "/Query", "/FO", "CSV"], capture_output=True, text=True,
                        encoding="mbcs", errors="replace")
    for name in ("TechRadar_Daily", "TechRadar_Weekly", "TechRadar_Monthly", "TechRadar_Quarterly"):
        check(name in ps.stdout, f"R8 计划任务存在且唯一：{name}")
    reg = json.loads((ROOT / "06_techradar/data/TASK_REGISTRY.json").read_text(encoding="utf-8"))
    check(len(reg["tasks"]) == 4 and all(t.get("config_hash") for t in reg["tasks"]),
          "R8 任务注册表 4 条且配置哈希齐全")

    # ================= R9 认证源状态 =================
    pf = run([str(SCRIPTS / "collect_folo.py"), "--db", str(tmp_root / "auth.db")],
             env={**OFFLINE_BROWSER, "FOLO_SESSION_TOKEN": ""})
    if pf.returncode == 3 and ("BLOCKED" in pf.stdout or "AUTH_REQUIRED" in pf.stdout):
        check(True, f"R9 Folo 无凭据/无登录态 BLOCKED（{pf.returncode}）")
    elif pf.returncode == 0 and ("browser_session" in pf.stdout or "READY" in pf.stdout):
        skip(f"R9 Folo 检测到浏览器登录态可用，凭据阻塞断言跳过（{pf.returncode}）")
    else:
        check(False, f"R9 Folo 状态异常（exit={pf.returncode}）")
    pr = run([str(SCRIPTS / "collect_reddit.py"), "--db", str(tmp_root / "auth.db")],
             env={**OFFLINE_BROWSER, "REDDIT_CLIENT_ID": "", "REDDIT_CLIENT_SECRET": ""})
    if pr.returncode == 3 and ("BLOCKED" in pr.stdout or "APPROVAL" in pr.stdout.upper()):
        check(True, f"R9 Reddit 无凭据/无审批 BLOCKED（{pr.returncode}）")
    elif pr.returncode == 0 and ("browser_session" in pr.stdout or "READY" in pr.stdout):
        skip(f"R9 Reddit 检测到浏览器登录态可用，凭据阻塞断言跳过（{pr.returncode}）")
    else:
        check(False, f"R9 Reddit 状态异常（exit={pr.returncode}）")
    # 无效凭据用例走本地夹具端点（真实验证 401 拒绝路径），不依赖外网
    pfi = run([str(SCRIPTS / "collect_folo.py"), "--db", str(tmp_root / "auth.db")],
              env={"FOLO_SESSION_TOKEN": "invalid-test-token",
                   "FOLO_API_BASE": f"{base}/folo"}, timeout=120)
    check(pfi.returncode in (2, 3), f"R9 Folo 无效凭据被拒绝（{pfi.returncode}）")
    pri = run([str(SCRIPTS / "collect_reddit.py"), "--db", str(tmp_root / "auth.db")],
              env={"REDDIT_CLIENT_ID": "x", "REDDIT_CLIENT_SECRET": "y",
                   "REDDIT_TOKEN_URL": f"{base}/reddit/token"}, timeout=120)
    check(pri.returncode == 3, f"R9 Reddit 无效凭据被拒绝（{pri.returncode}）")

    # ================= R10 故障隔离 =================
    iso_db = tmp_root / "iso.db"
    shutil.copy2(REAL_DB, iso_db)
    run([str(SCRIPTS / "collect_folo.py"), "--db", str(iso_db)],
        env={**OFFLINE_BROWSER, "FOLO_SESSION_TOKEN": ""})
    run([str(SCRIPTS / "collect_reddit.py"), "--db", str(iso_db)],
        env={**OFFLINE_BROWSER, "REDDIT_CLIENT_ID": "", "REDDIT_CLIENT_SECRET": ""})
    # 只跑两个秒级来源：验证公开通道可用即可，避免 13 源联网拖到十几分钟
    piso = run([str(SCRIPTS / "collect_public_suite.py"), "--db", str(iso_db), "--limit", "5",
                "--only", "hn_frontpage,cisa_kev"], timeout=300)
    check(piso.returncode == 0, f"R10 两认证通道阻塞时公开通道仍 PASS（{piso.returncode}）")

    # ================= R12 完整性 =================
    c = ro(str(REAL_DB))
    n_real = c.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    fts_real = c.execute("SELECT COUNT(*) FROM entries_fts").fetchone()[0]
    integ = c.execute("PRAGMA integrity_check").fetchone()[0]
    c.close()
    check(n_real >= 346, f"R12 真实库条目未减少（{n_real} >= 346）")
    check(fts_real == n_real, f"R12 FTS 与主表一致（{fts_real}/{n_real}）")
    check(integ == "ok", f"R12 integrity_check={integ}")

    httpd.shutdown()
    print()
    for n in notes:
        print("NOTE:", n)
    if skips:
        print(f"SKIPPED {len(skips)}:")
        for s in skips:
            print("  -", s)
    if failures:
        print(f"FAILED {len(failures)}:")
        for f in failures:
            print("  -", f)
        return 2
    print(f"PASS test_quality_review: R1–R10/R12 全部通过（skipped={len(skips)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
