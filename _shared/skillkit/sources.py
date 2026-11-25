"""统一 Source Registry：记录每个数据源的运行条件、授权状态、凭据状态与采集计数。

状态语义（严格区分，不得混为一谈）：
  READY            已具备运行条件（公开源或凭据有效）
  AUTH_REQUIRED    缺少凭证（补齐凭据即可运行）
  APPROVAL_REQUIRED 需要官方审批（如 Reddit Data API 的 app-registration / 访问审批）
  DEGRADED         当前异常，但不阻断其他来源
  DISABLED         用户主动禁用
  BLOCKED          确实存在不可解决的访问阻碍

授权状态 / 凭据状态 / 连通状态三者分列，互不替代。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

STATUSES = {"READY", "AUTH_REQUIRED", "APPROVAL_REQUIRED", "DEGRADED", "DISABLED", "BLOCKED"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_registry (
    source_id            TEXT PRIMARY KEY,
    source_name          TEXT NOT NULL,
    source_type          TEXT NOT NULL,     -- api | rss | atom | html | mcp
    channel              TEXT NOT NULL,     -- public | authenticated
    auth_required        INTEGER DEFAULT 0,
    authorization_status TEXT DEFAULT 'not_required',  -- not_required | pending | approved | rejected | unknown
    credential_status    TEXT DEFAULT 'not_required',   -- not_required | missing | invalid | valid
    connectivity_status  TEXT DEFAULT 'unknown',        -- unknown | online | offline | blocked
    status               TEXT DEFAULT 'READY',
    enabled              INTEGER DEFAULT 1,
    last_attempt_at      TEXT,
    last_success_at      TEXT,
    last_error           TEXT,
    items_fetched        INTEGER DEFAULT 0,
    items_inserted       INTEGER DEFAULT 0,
    items_deduped        INTEGER DEFAULT 0,
    notes                TEXT,
    updated_at           TEXT
);
"""

# v2 增量列：把"是否实现 / 是否配置 / 是否采集成功"从单一 status 中拆出来。
EXTRA_COLUMNS = {
    "implementation_status": "TEXT DEFAULT 'IMPLEMENTED'",  # IMPLEMENTED | NOT_IMPLEMENTED
    "configuration_status": "TEXT DEFAULT 'UNKNOWN'",       # CONFIGURED | UNCONFIGURED | PARTIAL | UNKNOWN
    "collection_status": "TEXT DEFAULT 'NEVER_RUN'",        # NEVER_RUN | SUCCESS | PARTIAL | FAILED | BLOCKED
    "last_checked_at": "TEXT",
}

STATUS_DOC = {
    "READY": "实现完成且具备运行条件（不代表最近一次在线或成功，需结合 connectivity/collection 判断）",
    "AUTH_REQUIRED": "缺少凭证，补齐即可运行",
    "APPROVAL_REQUIRED": "需要官方审批（如 Reddit app-registration 与访问审批）",
    "DEGRADED": "当前异常，但不阻断其他来源",
    "DISABLED": "用户主动禁用",
    "BLOCKED": "确实存在不可解决的访问阻碍",
}


def ensure_registry(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(source_registry)")}
    for col, decl in EXTRA_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE source_registry ADD COLUMN {col} {decl}")
    backfill_status(conn)
    conn.commit()


def backfill_status(conn: sqlite3.Connection) -> int:
    """按已有证据回填六态字段（幂等，只修正"未知/从未运行"的占位值）。

    依据：last_success_at 存在 → 确实成功过；auth_required 且凭据缺失 → 未配置/阻塞；
    无任何尝试记录 → NEVER_RUN / unknown。
    """
    cur = conn.execute("""
        UPDATE source_registry SET
            configuration_status = CASE
                WHEN auth_required=1 AND credential_status IN ('missing','invalid') THEN 'UNCONFIGURED'
                WHEN auth_required=0 THEN 'CONFIGURED'
                ELSE configuration_status END,
            collection_status = CASE
                WHEN last_success_at IS NOT NULL AND collection_status='NEVER_RUN' THEN 'SUCCESS'
                WHEN auth_required=1 AND credential_status IN ('missing','invalid') THEN 'BLOCKED'
                WHEN last_attempt_at IS NULL THEN 'NEVER_RUN'
                ELSE collection_status END,
            connectivity_status = CASE
                WHEN last_success_at IS NOT NULL AND connectivity_status='unknown' THEN 'ONLINE'
                ELSE connectivity_status END
        WHERE configuration_status='UNKNOWN'
           OR (collection_status='NEVER_RUN' AND last_success_at IS NOT NULL)
           OR (collection_status='NEVER_RUN' AND auth_required=1
               AND credential_status IN ('missing','invalid'))
    """)
    return cur.rowcount


def upsert_source(conn: sqlite3.Connection, source_id: str, source_name: str, source_type: str,
                   channel: str, *, auth_required: bool = False,
                   authorization_status: str = "not_required",
                   credential_status: str = "not_required",
                   connectivity_status: str = "unknown",
                   status: str = "READY", enabled: bool = True, notes: str | None = None,
                   implementation_status: str = "IMPLEMENTED",
                   configuration_status: str | None = None) -> None:
    if configuration_status is None:
        configuration_status = ("CONFIGURED" if credential_status in ("valid", "not_required")
                                else "UNCONFIGURED")
    conn.execute(
        "INSERT INTO source_registry(source_id,source_name,source_type,channel,auth_required,"
        "authorization_status,credential_status,connectivity_status,status,enabled,notes,updated_at,"
        "implementation_status,configuration_status,collection_status) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'NEVER_RUN') ON CONFLICT(source_id) DO UPDATE SET "
        "source_name=excluded.source_name, source_type=excluded.source_type, channel=excluded.channel, "
        "auth_required=excluded.auth_required, updated_at=excluded.updated_at, "
        "implementation_status=excluded.implementation_status",
        (source_id, source_name, source_type, channel, int(auth_required), authorization_status,
         credential_status, connectivity_status, status, int(enabled), notes,
         datetime.now().isoformat(timespec="seconds"), implementation_status, configuration_status))
    conn.commit()


def set_status(conn: sqlite3.Connection, source_id: str, status: str, *,
               authorization_status: str | None = None,
               credential_status: str | None = None,
               connectivity_status: str | None = None,
               collection_status: str | None = None,
               configuration_status: str | None = None,
               last_error: str | None = None,
               fetched: int = 0, inserted: int = 0, deduped: int = 0,
               attempted: bool = True, succeeded: bool = False) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    sets = ["status=?", "updated_at=?"]
    args: list[Any] = [status, now]
    for col, val in (("authorization_status", authorization_status),
                     ("credential_status", credential_status),
                     ("connectivity_status", connectivity_status),
                     ("collection_status", collection_status),
                     ("configuration_status", configuration_status)):
        if val is not None:
            sets.append(f"{col}=?")
            args.append(val)
    if last_error is not None:
        sets.append("last_error=?"); args.append(last_error[:500])
    if attempted:
        sets.append("last_attempt_at=?"); args.append(now)
        sets.append("last_checked_at=?"); args.append(now)
    if succeeded:
        sets.append("last_success_at=?"); args.append(now)
    sets += ["items_fetched=items_fetched+?", "items_inserted=items_inserted+?",
             "items_deduped=items_deduped+?"]
    args += [fetched, inserted, deduped]
    args.append(source_id)
    conn.execute(f"UPDATE source_registry SET {', '.join(sets)} WHERE source_id=?", args)
    conn.commit()


def list_sources(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM source_registry ORDER BY channel, source_id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["auth_required"] = bool(d["auth_required"])
        d["enabled"] = bool(d["enabled"])
        out.append(d)
    return out


def summary(conn: sqlite3.Connection) -> dict:
    rows = list_sources(conn)
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    return {
        "total": len(rows),
        "by_status": by_status,
        "fetched": sum(r["items_fetched"] for r in rows),
        "inserted": sum(r["items_inserted"] for r in rows),
        "deduped": sum(r["items_deduped"] for r in rows),
    }
