"""统一检索层：FTS5 全文 + 时间/标签/来源/关联过滤，FTS 不可用时自动降级为 LIKE。

设计原则：
- 不改动 entries 原表结构，只新增一张独立的 FTS5 虚表（可随时 DROP 回退）。
- 所有过滤条件可组合；FTS 失败不抛错，降级 LIKE 并在返回值里如实标明 engine。
- 关联检索只使用真实存在的两种关系：显式 relations 记录 + 同 canonical_key 的同主题条目。
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

FTS_TABLE = "entries_fts"
_SELECT = """
SELECT e.entry_id, e.title, e.url, e.summary, e.category, e.ai_category, e.corrected_category,
       e.origin_source, e.aggregator, e.published_at, e.first_seen_at, e.last_seen_at,
       e.link_status, e.canonical_key, e.metrics_json, e.extra_json, e.read_state,
       s.name AS source_name,
       (SELECT COUNT(*) FROM entries g WHERE g.canonical_key = e.canonical_key) AS cross_source_count,
       (SELECT GROUP_CONCAT(t.name) FROM entry_tags et JOIN tags t ON t.tag_id = et.tag_id
         WHERE et.entry_id = e.entry_id) AS tags
FROM entries e LEFT JOIN sources s ON s.source_id = e.source_id
"""


def fts_available(conn: sqlite3.Connection) -> bool:
    """判断当前 SQLite 是否启用 FTS5（只读安全：优先查 compile_options）。"""
    try:
        opts = [str(r[0]).upper() for r in conn.execute("PRAGMA compile_options")]
        if any("ENABLE_FTS5" in o for o in opts):
            return True
    except sqlite3.Error:
        pass
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp_fts_probe USING fts5(x)")
        conn.execute("DROP TABLE temp_fts_probe")
        return True
    except sqlite3.Error:
        return False


def fts_exists(conn: sqlite3.Connection) -> bool:
    """只读安全地判断 FTS 表是否已存在（不尝试建表）。"""
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (FTS_TABLE,)).fetchone()
        return bool(row)
    except sqlite3.Error:
        return False


def ensure_fts(conn: sqlite3.Connection) -> bool:
    """幂等创建 FTS5 表；不可用返回 False（调用方降级 LIKE）。只读连接上不会报错。"""
    if not fts_available(conn):
        return False
    try:
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5("
            "title, summary, body, url, category, origin_source, entry_id UNINDEXED)"
        )
        conn.commit()
        return True
    except sqlite3.Error:
        # 只读连接上无法建表，但表可能已存在
        return fts_exists(conn)


def _body_of(extra_json: str | None) -> str:
    try:
        extra = json.loads(extra_json) if extra_json else {}
    except (TypeError, json.JSONDecodeError):
        return ""
    if not isinstance(extra, dict):
        return ""
    return str(extra.get("content") or "")


def _body_from_articles(conn: sqlite3.Connection, entry_id: int) -> str:
    """优先取正文层（article_bodies）的成功正文；表不存在或没有则返回空串。

    RSS/API 的 summary 只有两三百字，真正能搜到技术细节的是这一列。
    """
    try:
        row = conn.execute(
            "SELECT body FROM article_bodies WHERE entry_id=? AND status='ok'",
            (int(entry_id),)).fetchone()
    except sqlite3.Error:
        return ""                     # 旧库还没有 article_bodies 表
    return (row[0] or "") if row else ""


def index_entry(conn: sqlite3.Connection, row: sqlite3.Row | dict) -> None:
    """把一条 entry 写入 FTS 索引（同一 entry_id 只保留一行，避免重复索引）。"""
    get = row.__getitem__ if not isinstance(row, dict) else row.get
    entry_id = get("entry_id")
    if entry_id is None:
        return
    body = _body_from_articles(conn, entry_id) or _body_of(get("extra_json"))
    conn.execute(f"DELETE FROM {FTS_TABLE} WHERE entry_id=?", (int(entry_id),))
    conn.execute(
        f"INSERT INTO {FTS_TABLE}(title, summary, body, url, category, origin_source, entry_id) "
        "VALUES(?,?,?,?,?,?,?)",
        (get("title") or "", get("summary") or "", body,
         get("url") or "", get("category") or "", get("origin_source") or "", int(entry_id)),
    )


def dedupe_fts(conn: sqlite3.Connection) -> int:
    """清理历史重复索引行：同一 entry_id 只保留最早一行。返回删除行数。"""
    try:
        cur = conn.execute(
            f"DELETE FROM {FTS_TABLE} WHERE rowid NOT IN "
            f"(SELECT MIN(rowid) FROM {FTS_TABLE} GROUP BY entry_id)")
        conn.commit()
        return cur.rowcount
    except sqlite3.Error:
        return 0


def rebuild_fts(conn: sqlite3.Connection) -> int:
    """全量重建索引（新增 FTS 后对历史数据回填）。"""
    if not ensure_fts(conn):
        return 0
    conn.execute(f"DELETE FROM {FTS_TABLE}")
    rows = conn.execute("SELECT * FROM entries").fetchall()
    for r in rows:
        index_entry(conn, r)
    conn.commit()
    return len(rows)


def drop_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute(f"DELETE FROM {FTS_TABLE} WHERE entry_id=?", (int(entry_id),))


def _fts_match_expr(text: str) -> str:
    """把用户输入转成安全的 FTS5 MATCH 表达式（逐词 OR，前缀匹配）。"""
    terms = [t.strip().replace('"', " ") for t in text.split() if t.strip()]
    if not terms:
        return ""
    return " OR ".join(f'"{t}"*' for t in terms[:24])


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _has_body_table(conn: sqlite3.Connection) -> bool:
    try:
        return bool(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='article_bodies'").fetchone())
    except sqlite3.Error:
        return False


def _like_clause(text: str, body: bool = False) -> tuple[str, list[str]]:
    terms = [t.strip() for t in text.split() if t.strip()]
    if not terms:
        return "", []
    clauses = []
    params: list[str] = []
    for t in terms[:24]:
        like = f"%{t.lower()}%"
        parts = ["LOWER(COALESCE(e.title,'')) LIKE ?",
                 "LOWER(COALESCE(e.summary,'')) LIKE ?",
                 "LOWER(COALESCE(e.extra_json,'')) LIKE ?",
                 "LOWER(COALESCE(e.category,'')) LIKE ?"]
        params.extend([like] * 4)
        if body:
            parts.append("e.entry_id IN (SELECT entry_id FROM article_bodies "
                         "WHERE status='ok' AND LOWER(COALESCE(body,'')) LIKE ?)")
            params.append(like)
        clauses.append("(" + " OR ".join(parts) + ")")
    return "(" + " OR ".join(clauses) + ")", params


def query_entries(conn: sqlite3.Connection, *, text: str | None = None,
                  since: str | None = None, until: str | None = None,
                  tags: list[str] | None = None, sources: list[str] | None = None,
                  related_to: int | None = None, limit: int = 20,
                  engine: str = "auto", order: str = "published_desc") -> dict[str, Any]:
    """组合查询。返回 {rows, engine, total, filters}。engine ∈ fts5 | like | none。

    CJK 检索说明：FTS5 unicode61 会把握手的中文整段当作单个 token，
    因此“甲骨文”这类子串查询会 0 命中。这里在 FTS 0 命中且含 CJK 时自动降级 LIKE，
    并把 article_bodies 正文层一并纳入 LIKE，保证中文正文可被召回。
    """
    conds: list[tuple[str, list[Any]]] = []
    used = "none"

    if text:
        clause = None
        cparams: list[Any] = []
        if engine in ("auto", "fts5"):
            try:
                fts_ok = ensure_fts(conn)
            except sqlite3.Error:
                fts_ok = fts_exists(conn)
            if fts_ok:
                # 索引自愈：FTS 行数少于 entries 说明索引未回填，尝试重建（需可写）
                try:
                    n_fts = conn.execute(f"SELECT COUNT(*) FROM {FTS_TABLE}").fetchone()[0]
                    n_all = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
                    if n_fts < n_all:
                        rebuild_fts(conn)
                except sqlite3.Error:
                    fts_ok = False
            if fts_ok:
                match = _fts_match_expr(text)
                if match:
                    clause = f"e.entry_id IN (SELECT entry_id FROM {FTS_TABLE} WHERE {FTS_TABLE} MATCH ?)"
                    cparams = [match]
                    used = "fts5"
        if clause is None:
            clause, cparams = _like_clause(text, _has_body_table(conn))
            used = "like" if clause else "none"
        if clause:
            conds.append((clause, cparams))

    if since:
        conds.append(("COALESCE(e.published_at, e.first_seen_at) >= ?", [since]))
    if until:
        conds.append(("COALESCE(e.published_at, e.first_seen_at) <= ?", [until]))
    if tags:
        names = [t.strip().lower() for t in tags if t.strip()]
        if names:
            marks = ",".join("?" * len(names))
            conds.append((f"e.entry_id IN (SELECT et.entry_id FROM entry_tags et JOIN tags t "
                          f"ON t.tag_id=et.tag_id WHERE t.name IN ({marks}))", names))
    if sources:
        names = [s.strip() for s in sources if s.strip()]
        if names:
            marks = ",".join("?" * len(names))
            conds.append((f"(COALESCE(e.origin_source,'direct') IN ({marks}) "
                          f"OR COALESCE(e.aggregator,'direct') IN ({marks}) "
                          f"OR COALESCE(s.name,'') IN ({marks}))", names + names + names))
    if related_to is not None:
        conds.append((
            "(e.canonical_key IS NOT NULL AND e.canonical_key = "
            "(SELECT canonical_key FROM entries WHERE entry_id=?) AND e.canonical_key <> '') "
            "OR e.entry_id IN (SELECT to_entry FROM relations WHERE from_entry=? "
            "UNION SELECT from_entry FROM relations WHERE to_entry=?)",
            [related_to, related_to, related_to]))

    def _run(items: list[tuple[str, list[Any]]]) -> list[sqlite3.Row]:
        sql = _SELECT
        if items:
            sql += " WHERE " + " AND ".join(c for c, _ in items)
        if order == "cross_source_desc":
            sql += " ORDER BY cross_source_count DESC, COALESCE(e.published_at, e.first_seen_at) DESC"
        elif order == "oldest":
            sql += " ORDER BY COALESCE(e.published_at, e.first_seen_at) ASC"
        else:
            sql += " ORDER BY COALESCE(e.published_at, e.first_seen_at) DESC"
        sql += " LIMIT ?"
        ps = [p for _, ps_ in items for p in ps_]
        return conn.execute(sql, ps + [int(limit)]).fetchall()

    def _switch_to_like() -> list[sqlite3.Row]:
        like_clause, lp = _like_clause(text or "", _has_body_table(conn))
        items = [(c, p) for c, p in conds if FTS_TABLE not in c]
        if like_clause:
            items = [(like_clause, lp)] + items
        return _run(items)

    try:
        rows = _run(conds)
    except sqlite3.Error:
        if used != "fts5":
            raise
        rows = _switch_to_like()
        used = "like"

    # CJK 子串在 FTS5 下常常 0 命中，自动降级 LIKE（含正文层）
    if used == "fts5" and not rows and text and _has_cjk(text):
        rows = _switch_to_like()
        used = "like"

    out = []
    for r in rows:
        d = dict(r)
        try:
            d["metrics"] = json.loads(d.pop("metrics_json") or "{}")
        except json.JSONDecodeError:
            d["metrics"] = {}
        d["tags"] = [t for t in (d.get("tags") or "").split(",") if t]
        out.append(d)
    return {"rows": out, "engine": used, "count": len(out),
            "filters": {"text": text, "since": since, "until": until,
                        "tags": tags, "sources": sources, "related_to": related_to}}
