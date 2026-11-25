#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scheduler.py — TechRadar 定时任务注册器（Windows 任务计划程序）。

特性：
- 幂等：已存在则比对配置哈希，仅在不一致时 /Change，不重复创建。
- 机器可读注册表：06_techradar/data/TASK_REGISTRY.json + SQLite task_registry 表。
- 跨客户端接管：新 Agent 读注册表即可识别已有任务，不需要重建。
- 首次触发测试：schtasks /Run 后回查 job_runs 是否新增，如实报告。
- 不支持后台任务的环境（非 Windows 且无 cron）明确 BLOCKED，并给替代命令。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))
from skillkit.inteldb import IntelDB  # noqa: E402

DB = ROOT / "06_techradar" / "data" / "techradar.db"
REGISTRY = ROOT / "06_techradar" / "data" / "TASK_REGISTRY.json"
RUNNER = ROOT / "06_techradar" / "scripts" / "lifecycle_run.py"
WRAPPER_DIR = ROOT / "06_techradar" / "scripts" / "tasks"
LOG_DIR = ROOT / "_logs" / "scheduler"
PY = sys.executable

SKILL_VERSION = "1.2.0"

# 四类周期任务；weekly/monthly 的清理默认 dry-run（config.apply_purge=false 时强制执行 dry-run）
TASKS = [
    {
        "key": "TechRadar_Daily",
        "name": "TechRadar 每日采集",
        "schedule": "DAILY 07:30",
        "args": ["--job", "daily"],
        "desc": "采集 Folo/Reddit/GitHub/资源雷达，去重入库、更新状态与价值分",
    },
    {
        "key": "TechRadar_Weekly",
        "name": "TechRadar 每周体检",
        "schedule": "WEEKLY SUN 08:00",
        "args": ["--job", "weekly"],
        "desc": "来源健康、失效链接、重复内容、低价值清理计划",
    },
    {
        "key": "TechRadar_Monthly",
        "name": "TechRadar 每月维护",
        "schedule": "MONTHLY 1 09:00",
        "args": ["--job", "monthly"],
        "desc": "备份、完整性检查、价值重评、快照降采样",
    },
    {
        "key": "TechRadar_Quarterly",
        "name": "TechRadar 每季审计",
        "schedule": "MONTHLY 1 JAN,APR,JUL,OCT 10:00",
        "args": ["--job", "quarterly"],
        "desc": "信息源审计、档案与库结构审计、采集策略建议",
    },
]


def config_hash(task: dict) -> str:
    payload = json.dumps({"args": task["args"], "script": str(RUNNER), "skill": SKILL_VERSION,
                          "schedule": task["schedule"]}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def is_windows() -> bool:
    return platform.system().lower() == "windows"


def schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True,
                          encoding="mbcs", errors="replace")


def task_exists(key: str) -> bool:
    p = schtasks("/Query", "/TN", key)
    return p.returncode == 0


def task_action(key: str) -> str:
    """读取已注册任务的执行命令行（用于识别冲突/漂移）。"""
    p = schtasks("/Query", "/TN", key, "/FO", "LIST", "/V")
    for line in p.stdout.splitlines():
        if "Task To Run" in line or "要运行的任务" in line:
            return line.split(":", 1)[-1].strip()
    return ""


def write_wrapper(task: dict) -> Path:
    """生成 .cmd 包装脚本：固定工作目录、日志重定向，避免控制台型任务被计划程序终止。"""
    WRAPPER_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = WRAPPER_DIR / f"{task['key'].replace('TechRadar_', '').lower()}.cmd"
    cmd = (f'@"{PY}" "{RUNNER}" {" ".join(task["args"])} '
           f'>> "{LOG_DIR / (path.stem + ".log")}" 2>&1\r\n')
    content = ("@echo off\r\n"
               "chcp 65001 >nul\r\n"
               f'cd /d "{ROOT}"\r\n'
               f"{cmd}"
               "exit /b %ERRORLEVEL%\r\n")
    path.write_text(content, encoding="utf-8")
    return path


def build_action(task: dict) -> str:
    """计划任务的执行目标：cmd 包装脚本（路径无空格，避免引号歧义）。"""
    return str(WRAPPER_DIR / f"{task['key'].replace('TechRadar_', '').lower()}.cmd")


def create_or_update(task: dict) -> dict:
    key = task["key"]
    wrapper = write_wrapper(task)
    action = build_action(task)
    sched = task["schedule"].split()
    kind = sched[0]
    record = {"task_key": key, "name": task["name"], "schedule": task["schedule"],
              "script_path": str(RUNNER), "args": " ".join(task["args"]),
              "skill_version": SKILL_VERSION, "action": action,
              "wrapper": str(wrapper),
              "action_command": f'"{PY}" "{RUNNER}" {" ".join(task["args"])}',
              "config_hash": config_hash(task)}

    if task_exists(key):
        current = task_action(key)
        if current.strip().strip('"') == action.strip().strip('"'):
            record["result"] = "EXISTS_OK"
        else:
            p = schtasks("/Change", "/TN", key, "/TR", action)
            record["result"] = "UPDATED" if p.returncode == 0 else f"CHANGE_FAILED({p.returncode})"
            if p.returncode != 0:
                record["error"] = p.stderr.strip()[:300]
        return record

    if kind == "DAILY":
        cmd = ["/Create", "/TN", key, "/TR", action, "/SC", "DAILY", "/ST", sched[1], "/F"]
    elif kind == "WEEKLY":
        cmd = ["/Create", "/TN", key, "/TR", action, "/SC", "WEEKLY",
               "/D", sched[1], "/ST", sched[2], "/F"]
    elif kind == "MONTHLY" and len(sched) == 5:
        cmd = ["/Create", "/TN", key, "/TR", action, "/SC", "MONTHLY",
               "/M", sched[2], "/ST", sched[4],
               "/D", "1"]
    elif kind == "MONTHLY":
        cmd = ["/Create", "/TN", key, "/TR", action, "/SC", "MONTHLY",
               "/D", "1", "/ST", sched[2], "/F"]
    else:
        record["result"] = "SKIPPED_UNSUPPORTED_SCHEDULE"
        return record
    p = schtasks(*cmd)
    record["result"] = "CREATED" if p.returncode == 0 else f"CREATE_FAILED({p.returncode})"
    if p.returncode != 0:
        record["error"] = (p.stderr or p.stdout).strip()[:300]
    return record


def quarterly_create(task: dict) -> dict:
    """季度任务：Windows 用 MONTHLY + 多月份；避免 /SC MONTHLY 不支持月份列表的限制。"""
    key = task["key"]
    wrapper = write_wrapper(task)
    action = build_action(task)
    if task_exists(key):
        current = task_action(key)
        if current.strip().strip('"') == action.strip().strip('"'):
            return {**meta(task), "result": "EXISTS_OK", "wrapper": str(wrapper)}
        p = schtasks("/Change", "/TN", key, "/TR", action)
        return {**meta(task), "result": "UPDATED" if p.returncode == 0 else "CHANGE_FAILED",
                "wrapper": str(wrapper)}
    p = schtasks("/Create", "/TN", key, "/TR", action, "/SC", "MONTHLY",
                 "/M", "JAN,APR,JUL,OCT", "/D", "1", "/ST", "10:00", "/F")
    return {**meta(task), "result": "CREATED" if p.returncode == 0 else f"CREATE_FAILED({p.returncode})",
            "wrapper": str(wrapper),
            **({"error": (p.stderr or p.stdout).strip()[:300]} if p.returncode else {})}


def meta(task: dict) -> dict:
    return {"task_key": task["key"], "name": task["name"], "schedule": task["schedule"],
            "script_path": str(RUNNER), "args": " ".join(task["args"]),
            "skill_version": SKILL_VERSION, "action": build_action(task),
            "wrapper": build_action(task),
            "action_command": f'"{PY}" "{RUNNER}" {" ".join(task["args"])}',
            "config_hash": config_hash(task)}


def sync_registry(records: list[dict]) -> None:
    """同时写 JSON 文件与 SQLite 表，供任意客户端读取。"""
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if REGISTRY.exists():
        try:
            existing = json.loads(REGISTRY.read_text(encoding="utf-8")).get("tasks", [])
        except json.JSONDecodeError:
            existing = []
    merged = {t["task_key"]: t for t in existing}
    for r in records:
        prev = merged.get(r["task_key"], {})
        merged[r["task_key"]] = {
            "last_run_at": None, "last_status": None,
            **prev, **{k: v for k, v in r.items() if k != "result"},
            "last_result": r.get("result"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    payload = {
        "schema": "techradar-task-registry-v1",
        "skill_version": SKILL_VERSION,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "runner": str(RUNNER),
        "python": PY,
        "database": str(DB),
        "config": str(ROOT / "06_techradar" / "data" / "lifecycle_config.json"),
        "scheduler": "windows-task-scheduler" if is_windows() else "unsupported",
        "tasks": list(merged.values()),
    }
    REGISTRY.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with IntelDB(DB) as db:
        for t in merged.values():
            db.conn.execute(
                "INSERT INTO task_registry(task_key,name,schedule,script_path,args,skill_version,"
                "last_run_at,last_status,registered_at,config_hash) VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(task_key) DO UPDATE SET name=excluded.name, schedule=excluded.schedule, "
                "script_path=excluded.script_path, args=excluded.args, skill_version=excluded.skill_version, "
                "registered_at=excluded.registered_at, config_hash=excluded.config_hash",
                (t["task_key"], t["name"], t["schedule"], str(RUNNER), t.get("args"),
                 SKILL_VERSION, t.get("last_run_at"), t.get("last_status"),
                 t.get("updated_at"), t.get("config_hash")),
            )
        db.conn.commit()


def action_status() -> int:
    """只读巡检：不执行迁移、不写库、不改 mtime、不动计划任务。"""
    print(f"platform={platform.system()} scheduler={'schtasks' if is_windows() else 'none'}")
    if not REGISTRY.exists():
        print("REGISTRY: MISSING（尚未安装定时任务）")
    else:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        print(f"REGISTRY: {REGISTRY}  skill_version={data.get('skill_version')}")
        for t in data.get("tasks", []):
            exists = task_exists(t["task_key"]) if is_windows() else False
            print(f"  {t['task_key']:24s} schedule={t['schedule']:32s} "
                  f"registered={'YES' if exists else 'NO'} last={t.get('last_run_at')} "
                  f"status={t.get('last_status')}")
    if is_windows():
        p = schtasks("/Query", "/FO", "TABLE")
        lines = [ln for ln in p.stdout.splitlines() if "TechRadar_" in ln]
        print("SCHTASKS:")
        for ln in lines:
            print("  " + " ".join(ln.split())[:160])
    # 情报库用只读连接，避免任何迁移或写入
    if DB.exists():
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT job_name, mode, started_at, finished_at, status, collected, inserted, purged "
                "FROM job_runs ORDER BY run_id DESC LIMIT 8").fetchall()
            print("RECENT RUNS:")
            for r in rows:
                print(f"  #{r[0]} {r[1]} {r[2]} -> {r[3]} {r[4]} collected={r[5]} inserted={r[6]} purged={r[7]}")
            schema = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            n = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            print(f"DB: entries={n} schema={schema[0] if schema else 'unknown'} bytes={DB.stat().st_size}")
        finally:
            conn.close()
    return 0


def action_install() -> int:
    if not is_windows():
        print("BLOCKED: 当前环境不是 Windows，未创建任务。")
        print("替代方案（cron）：")
        print(f"  30 7 * * * cd {ROOT} && {PY} {RUNNER} --job daily")
        print("  0 8 * * 0 ...weekly   /   0 9 1 * * ...monthly   /   0 10 1 1,4,7,10 * ...quarterly")
        return 3
    records = []
    for task in TASKS:
        records.append(quarterly_create(task) if task["key"] == "TechRadar_Quarterly"
                       else create_or_update(task))
        print(f"{records[-1]['result']:16s} {records[-1]['task_key']}  ({records[-1]['schedule']})")
        if records[-1].get("error"):
            print("   error:", records[-1]["error"])
    sync_registry(records)
    print(f"REGISTRY -> {REGISTRY}")
    return 0 if all(r["result"] in ("CREATED", "EXISTS_OK", "UPDATED") for r in records) else 2


def action_trigger_test() -> int:
    """触发已验证任务一次，回查 job_runs 是否真实新增。"""
    key = "TechRadar_Daily"
    with IntelDB(DB) as db:
        before = db.conn.execute("SELECT COALESCE(MAX(run_id),0) FROM job_runs").fetchone()[0]
    p = schtasks("/Run", "/TN", key)
    print(f"schtasks /Run {key} -> exit={p.returncode} {(p.stdout or p.stderr).strip()[:160]}")
    if p.returncode != 0:
        print("TRIGGER: FAIL（任务未启动）")
        return 2
    deadline = datetime.now() + timedelta(minutes=6)
    last = None
    while datetime.now() < deadline:
        time.sleep(8)
        with IntelDB(DB) as db:
            row = db.conn.execute(
                "SELECT run_id, job_name, mode, started_at, finished_at, status, inserted "
                "FROM job_runs WHERE run_id>? ORDER BY run_id DESC LIMIT 1", (before,)).fetchone()
        if row and row[4]:
            last = row
            break
        time.sleep(4)
    if not last:
        print("TRIGGER: FAIL（6 分钟内未见 job_runs 新记录）")
        return 2
    print(f"TRIGGER: PASS run_id={last[0]} job={last[1]} mode={last[2]} "
          f"{last[3]} -> {last[4]} status={last[5]} inserted={last[6]}")

    with IntelDB(DB) as db:
        db.conn.execute("UPDATE task_registry SET last_run_at=?, last_status=? WHERE task_key=?",
                        (last[4], last[5], key))
        db.conn.commit()
    if REGISTRY.exists():
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        for t in data.get("tasks", []):
            if t["task_key"] == key:
                t["last_run_at"], t["last_status"] = last[4], last[5]
        REGISTRY.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def action_remove() -> int:
    if not is_windows():
        print("BLOCKED: 非 Windows")
        return 3
    failed = 0
    for t in TASKS:
        p = schtasks("/Delete", "/TN", t["key"], "/F")
        print(f"{'DELETED' if p.returncode == 0 else 'NOT_FOUND'}: {t['key']}")
        failed += p.returncode != 0
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--action", required=True, choices=["status", "install", "remove", "trigger-test"])
    args = ap.parse_args()
    return {"status": action_status, "install": action_install,
            "remove": action_remove, "trigger-test": action_trigger_test}[args.action]()


if __name__ == "__main__":
    raise SystemExit(main())
