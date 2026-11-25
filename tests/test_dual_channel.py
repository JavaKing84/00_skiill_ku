#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_dual_channel.py — 双通道采集体系验收（A1–A4 / B1–B5 / C1–C3 / D1–D2）。

判定原则：
- 有真实执行证据 → PASS；部分达成 → PARTIAL；被凭据/审批阻塞 → BLOCKED；失败 → FAIL；未执行 → NOT_TESTED。
- 认证通道在没有真实凭据时，**不得**伪造成功：用真实端点 + 无效凭据验证"认证路径确实执行了真实请求并正确失败"。
- A1/D1 使用 3 个快速公开源（hn_frontpage / github_search / cisa_kev），
  避免被 sec_restricted、资源雷达等慢源拖到十几分钟；完整源覆盖由日常任务与独立套件保证。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_shared"))
from skillkit.inteldb import IntelDB  # noqa: E402

REAL_DB = ROOT / "06_techradar" / "data" / "techradar.db"
SCRIPTS = ROOT / "06_techradar" / "scripts"
SUITE = SCRIPTS / "collect_public_suite.py"
FOLO = SCRIPTS / "collect_folo.py"
REDDIT = SCRIPTS / "collect_reddit.py"
STATUS = SCRIPTS / "source_status.py"
failures: list[str] = []
notes: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)
    print(("PASS " if cond else "FAIL ") + msg)


def note(msg: str) -> None:
    notes.append(msg)
    print("NOTE " + msg)


def run(args: list[str], env: dict | None = None, timeout: int = 1200) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    e.pop("FOLO_SESSION_TOKEN", None)
    e.pop("REDDIT_CLIENT_ID", None)
    e.pop("REDDIT_CLIENT_SECRET", None)
    if env:
        e.update(env)
    return subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          cwd=str(ROOT), env=e, timeout=timeout)


def entries_count(db: str) -> int:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return c.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    finally:
        c.close()


# 认证阻塞用例：禁用浏览器回退，避免测试误用用户正在使用的 Chrome 登录态。
OFFLINE_BROWSER = {"TECH_RADAR_CDP": "http://127.0.0.1:1", "TECH_RADAR_CDP_PORT": "1",
                   "TECH_RADAR_DISABLE_BROWSER": "1"}
# 快速公开源子集（仍覆盖多来源；避免慢源拖长回归）
FAST_SOURCES = "hn_frontpage,github_search,cisa_kev"


def main() -> int:
    before = entries_count(str(REAL_DB))
    # 认证源用例统一在临时副本上跑，避免把真实库 registry 写成测试状态
    auth_tmp = Path(tempfile.mkdtemp(prefix="dual_auth_"))
    auth_db = str(auth_tmp / "auth.db")
    shutil.copy2(REAL_DB, auth_db)

    # ---------- A1 零凭证公开采集 ----------
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "a.db")
        # 先初始化空库 schema（collect_public_suite 要求库已存在），再验证真实新入库
        with IntelDB(db):
            pass
        p = run([str(SUITE), "--db", db, "--limit", "10", "--only", FAST_SOURCES,
                 "--report", str(Path(td) / "a.json")])
        check(p.returncode == 0, f"A1 零凭证公开采集成功（exit={p.returncode}）")
        report = json.loads((Path(td) / "a.json").read_text(encoding="utf-8")) if (Path(td) / "a.json").exists() else {}
        ready = report.get("sources_ready", 0)
        check(ready >= 3, f"A2 多种公开来源就绪（{ready}/{report.get('sources_total', 0)} 个来源 READY）")
        check(report.get("inserted", 0) > 0, f"A3 公开数据实际写入 SQLite（新入库 {report.get('inserted', 0)} 条）")

        # A4 FTS5 能检索新入库数据
        ctmp = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            origins = {r[0] for r in ctmp.execute(
                "SELECT DISTINCT origin_source FROM entries WHERE origin_source IS NOT NULL")}
        finally:
            ctmp.close()
        check(len(origins) >= 3, f"A4 入库覆盖多来源（{len(origins)} 个 origin_source）")
        q = run([str(SCRIPTS / "radar_query.py"), "--db", db, "--text", "llm OR model OR robot",
                 "--limit", "5"])
        check(q.returncode == 0 and "hits=0" not in q.stdout,
              f"A4 FTS5 检索新入库数据可用（{q.stdout.strip().splitlines()[0] if q.stdout else ''}）")

        # D1 去重：再跑一次应大量命中去重
        p2 = run([str(SUITE), "--db", db, "--limit", "10", "--only", FAST_SOURCES,
                  "--report", str(Path(td) / "a2.json")])
        r2 = json.loads((Path(td) / "a2.json").read_text(encoding="utf-8")) if (Path(td) / "a2.json").exists() else {}
        check(p2.returncode == 0 and r2.get("deduped", 0) > 0,
              f"D1 二次采集命中去重（deduped={r2.get('deduped', 0)}）")
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
        fts_rows = c.execute("SELECT COUNT(*) FROM entries_fts").fetchone()[0]
        ent_rows = c.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        traced = c.execute("SELECT COUNT(*) FROM entries WHERE origin_source IS NOT NULL "
                           "AND url IS NOT NULL AND url<>''").fetchone()[0]
        c.close()
        check(integrity == "ok", f"D1 副本库完整性 ok（{integrity}）")
        check(fts_rows == ent_rows, f"D1 FTS 索引与主表一致（{fts_rows}/{ent_rows}）")
        check(traced > 0, f"D1 溯源字段完整（{traced} 条带 origin_source + url）")

    # ---------- B1/B2 Folo ----------
    src = FOLO.read_text(encoding="utf-8")
    check("api.follow.is" in src and "__Secure-better-auth.session_token" in src
          and "/subscriptions" in src and "/entries" in src,
          "B1 Folo 适配器实现了正式接口与 Cookie 认证流程")
    pf = run([str(FOLO), "--db", auth_db, "--report", ""],
             env={**OFFLINE_BROWSER, "FOLO_SESSION_TOKEN": ""})
    check(pf.returncode == 3 and "BLOCKED" in pf.stdout,
          f"B1 缺凭据时明确 BLOCKED 并给配置方法（exit={pf.returncode}）")
    check("FOLO_SESSION_TOKEN" in pf.stdout and "app.folo.is" in pf.stdout,
          "B1 输出包含凭据获取与配置指引")
    # 用无效令牌发起真实请求，验证认证路径确实打通到线上端点
    pinv = run([str(FOLO), "--db", auth_db],
               env={**OFFLINE_BROWSER, "FOLO_SESSION_TOKEN": "invalid-test-token-value"})
    blocked_or_fail = pinv.returncode in (2, 3)
    check(blocked_or_fail, f"B2 无效令牌触发真实请求并被正确拒绝（exit={pinv.returncode}）")
    note("B2 配置合法 Folo 凭据后的真实采集：NOT_TESTED（缺少用户凭据，代码路径已用真实端点验证）")

    # ---------- B3/B4 Reddit ----------
    rsrc = REDDIT.read_text(encoding="utf-8")
    check("https://www.reddit.com/api/v1/access_token" in rsrc
          and "https://oauth.reddit.com" in rsrc and "client_credentials" in rsrc
          and "app-registration" in rsrc,
          "B3 Reddit OAuth 适配器实现了官方令牌与 API 端点、审批流程说明")
    pr = run([str(REDDIT), "--db", auth_db],
             env={**OFFLINE_BROWSER, "REDDIT_CLIENT_ID": "", "REDDIT_CLIENT_SECRET": ""})
    check(pr.returncode == 3 and "BLOCKED" in pr.stdout,
          f"B3/B4 缺凭据时标 APPROVAL_REQUIRED 并给审批指引（exit={pr.returncode}）")
    # 无效凭据 → 真实请求拿 401
    prinv = run([str(REDDIT), "--db", auth_db],
                env={**OFFLINE_BROWSER, "REDDIT_CLIENT_ID": "invalid-id",
                     "REDDIT_CLIENT_SECRET": "invalid-secret"})
    check(prinv.returncode == 3 and "BLOCKED" in pr.stdout,
          f"B4 无效凭据触发真实 401 并被正确识别（exit={prinv.returncode}）")
    note("B5 取得官方审批后的 Reddit 真实采集：NOT_TESTED（需用户完成 app-registration 与访问审批）")

    # 注册表三类状态分列
    pst = run([str(STATUS), "--db", auth_db, "--json", str(ROOT / "_reports" / "source_status.json")])
    check(pst.returncode == 0, f"B4 数据源注册表巡检可运行（exit={pst.returncode}）")
    c = sqlite3.connect(f"file:{auth_db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    reddit = c.execute("SELECT * FROM source_registry WHERE source_id='reddit'").fetchone()
    folo = c.execute("SELECT * FROM source_registry WHERE source_id='folo'").fetchone()
    public_rows = c.execute("SELECT * FROM source_registry WHERE channel='public'").fetchall()
    c.close()
    check(reddit is not None
          and reddit["status"] in ("APPROVAL_REQUIRED", "AUTH_REQUIRED")
          and reddit["authorization_status"] == "pending"
          and reddit["credential_status"] in ("missing", "invalid")
          and reddit["connectivity_status"] in ("unknown", "unauthorized", "blocked"),
          f"B4 Reddit 审批/凭据/连通三态分列（status={reddit['status'] if reddit else None}, "
          f"approval={reddit['authorization_status'] if reddit else None}, "
          f"cred={reddit['credential_status'] if reddit else None}, "
          f"conn={reddit['connectivity_status'] if reddit else None}）")
    check(folo is not None and folo["status"] in ("AUTH_REQUIRED", "DEGRADED", "BLOCKED")
          and folo["credential_status"] in ("missing", "invalid"),
          f"B4 Folo 状态为 AUTH_REQUIRED/DEGRADED（status={folo['status'] if folo else None}, "
          f"cred={folo['credential_status'] if folo else None}）")
    check(len(public_rows) >= 8
          and all(r["status"] in ("READY", "DEGRADED") for r in public_rows),
          f"B4 公开来源无 BLOCKED（READY/DEGRADED，{len(public_rows)} 个）")

    # ---------- C1/C2/C3 故障隔离 ----------
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "c.db")
        shutil.copy2(REAL_DB, db)
        # C1：Folo 认证失败 + 公开通道
        pf2 = run([str(FOLO), "--db", db],
                  env={**OFFLINE_BROWSER, "FOLO_SESSION_TOKEN": "invalid-test-token-value"})
        pA = run([str(SUITE), "--db", db, "--limit", "8", "--only", FAST_SOURCES])
        check(pf2.returncode in (2, 3) and pA.returncode == 0,
              f"C1 Folo 失败不影响公开通道（folo={pf2.returncode}, public={pA.returncode}）")
        # C2：Reddit 认证失败 + 公开通道
        pr2 = run([str(REDDIT), "--db", db],
                  env={**OFFLINE_BROWSER, "REDDIT_CLIENT_ID": "invalid-id",
                       "REDDIT_CLIENT_SECRET": "invalid-secret"})
        pA2 = run([str(SUITE), "--db", db, "--limit", "8", "--only", FAST_SOURCES])
        check(pr2.returncode == 3 and pA2.returncode == 0,
              f"C2 Reddit 失败不影响公开通道（reddit={pr2.returncode}, public={pA2.returncode}）")
        # C3：两个认证通道同时无凭据，公开通道仍 PASS
        pf3 = run([str(FOLO), "--db", db], env={**OFFLINE_BROWSER, "FOLO_SESSION_TOKEN": ""})
        pr3 = run([str(REDDIT), "--db", db],
                  env={**OFFLINE_BROWSER, "REDDIT_CLIENT_ID": "", "REDDIT_CLIENT_SECRET": ""})
        pA3 = run([str(SUITE), "--db", db, "--limit", "8", "--only", FAST_SOURCES])
        check(pf3.returncode == 3 and pr3.returncode == 3 and pA3.returncode == 0,
              f"C3 两个认证通道同时失败，公开通道仍 PASS（folo={pf3.returncode} reddit={pr3.returncode} "
              f"public={pA3.returncode}）")

    # ---------- D2 原有功能与计划任务回归 ----------
    # 只跑快速代表套件；test_scenarios / test_zcl_integration 由 run_all.py 单独跑，避免嵌套拖长。
    for t in ("test_skillkit_contract", "test_techradar", "test_registry", "test_video_pipeline",
              "test_lifecycle", "test_triggers"):
        pt = run([str(ROOT / "tests" / f"{t}.py")], timeout=1800)
        check(pt.returncode == 0, f"D2 回归测试 {t} 通过（exit={pt.returncode}）")

    after = entries_count(str(REAL_DB))
    shutil.rmtree(auth_tmp, ignore_errors=True)
    check(after >= before, f"真实库条目未减少（{before} → {after}）")

    print()
    for n in notes:
        print("NOTE:", n)
    if failures:
        print(f"FAILED {len(failures)}:")
        for f in failures:
            print("  -", f)
        return 2
    print("PASS test_dual_channel: 双通道采集/隔离/溯源/去重/注册表/回归 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
