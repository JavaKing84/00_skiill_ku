"""入库前溯源校验与隔离区。

规则（对应质量整改第 4 项）：
- 新采集记录必须有可解析的原始 URL 与有效 origin_source；
- 聚合源必须区分 aggregator（渠道）与 origin_source（真实上游）；
- 校验失败不静默入库，写入 provenance_quarantine 待修复，并计入 skipped；
- 历史存量数据不追溯、不改写、不编造 URL。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

SCHEMA = """
CREATE TABLE IF NOT EXISTS provenance_quarantine (
    quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id     TEXT,
    reason        TEXT NOT NULL,
    url           TEXT,
    title         TEXT,
    payload_json  TEXT,
    created_at    TEXT NOT NULL,
    status        TEXT DEFAULT 'PENDING',   -- PENDING | FIXED | DISCARDED
    note          TEXT
);
CREATE INDEX IF NOT EXISTS idx_quarantine_status ON provenance_quarantine(status);
"""

VALID_SCHEMES = ("http", "https")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def validate(url: str | None, origin_source: str | None, aggregator: str | None = None) -> tuple[bool, str]:
    """返回 (是否通过, 失败原因)。"""
    if not url or not str(url).strip():
        return False, "missing_url"
    try:
        parts = urlparse(str(url).strip())
    except ValueError:
        return False, "invalid_url"
    if parts.scheme not in VALID_SCHEMES or not parts.netloc:
        return False, "invalid_url"
    if not origin_source or not str(origin_source).strip():
        return False, "missing_origin_source"
    if aggregator and str(origin_source).strip() == str(aggregator).strip():
        # 聚合渠道不能把自己当成上游来源
        return False, "aggregator_as_origin"
    return True, "ok"


def quarantine(conn: sqlite3.Connection, *, source_id: str, reason: str,
               url: str | None, title: str | None, payload: dict[str, Any]) -> int:
    ensure_schema(conn)
    cur = conn.execute(
        "INSERT INTO provenance_quarantine(source_id,reason,url,title,payload_json,created_at,status) "
        "VALUES(?,?,?,?,?,?,'PENDING')",
        (source_id, reason, url, title,
         json.dumps(payload, ensure_ascii=False, default=str)[:8000],
         datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    return int(cur.lastrowid)


def summary(conn: sqlite3.Connection) -> dict:
    """隔离区统计（按原因与状态）。"""
    ensure_schema(conn)
    by_reason = {r[0]: r[1] for r in conn.execute(
        "SELECT reason, COUNT(*) FROM provenance_quarantine GROUP BY reason")}
    by_status = {r[0]: r[1] for r in conn.execute(
        "SELECT status, COUNT(*) FROM provenance_quarantine GROUP BY status")}
    return {"by_reason": by_reason, "by_status": by_status,
            "total": sum(by_reason.values())}
