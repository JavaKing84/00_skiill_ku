"""TechRadar 本地情报库（SQLite）。

表：sources / entries / projects / tags / insights / relations / snapshots / analysis_runs。
去重：entries.content_hash 唯一索引（URL + 标题归一化哈希），重复采集走 INSERT OR IGNORE。
仅依赖标准库 sqlite3，跨客户端零外部依赖。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sources (
    source_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    kind        TEXT NOT NULL,           -- folo | reddit | github | hn | rss | web
    base_url    TEXT,
    auth_state  TEXT DEFAULT 'unknown',  -- ok | auth_required | unavailable | degraded
    note        TEXT
);
CREATE TABLE IF NOT EXISTS entries (
    entry_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id     INTEGER REFERENCES sources(source_id),
    url           TEXT NOT NULL,
    title         TEXT,
    author        TEXT,
    published_at  TEXT,
    collected_at  TEXT NOT NULL,
    summary       TEXT,
    content_hash  TEXT NOT NULL UNIQUE,
    read_state    TEXT DEFAULT 'title_scanned', -- title_scanned | body_read | comments_read | deep_read
    metrics_json  TEXT,
    extra_json    TEXT
);
CREATE TABLE IF NOT EXISTS projects (
    project_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tags (
    tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name   TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS entry_tags (
    entry_id INTEGER REFERENCES entries(entry_id),
    tag_id   INTEGER REFERENCES tags(tag_id),
    PRIMARY KEY (entry_id, tag_id)
);
CREATE TABLE IF NOT EXISTS insights (
    insight_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER REFERENCES projects(project_id),
    created_at    TEXT NOT NULL,
    claim         TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    confidence    TEXT DEFAULT 'medium'   -- low | medium | high
);
CREATE TABLE IF NOT EXISTS relations (
    relation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_entry  INTEGER REFERENCES entries(entry_id),
    to_entry    INTEGER REFERENCES entries(entry_id),
    relation    TEXT NOT NULL,            -- combo | contradicts | extends
    note        TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    INTEGER REFERENCES entries(entry_id),
    taken_at    TEXT NOT NULL,
    metrics_json TEXT
);
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    question     TEXT,
    coverage_json TEXT,
    status       TEXT DEFAULT 'running'
);
"""


def content_hash_for(url: str, title: str | None) -> str:
    norm = (url.strip().lower() + "|" + (title or "").strip()).encode("utf-8")
    return hashlib.sha256(norm).hexdigest()


# ---- Schema v2 增量迁移（2026-11-17，资源雷达接入）----
# 全部为 ADD COLUMN，可空、带默认值，旧数据零破坏；每步幂等。
V2_COLUMNS = {
    "external_key": "TEXT",          # 采集渠道内唯一条目键，如 zcl:41238；幂等 upsert 锚点
    "origin_source": "TEXT",         # 聚合器上游源 ID，如 tg-cn-deals/github-awesome-ai；直采为 NULL
    "aggregator": "TEXT",            # 聚合渠道名，如 radar.zichuanlan.top；直采为 NULL
    "canonical_key": "TEXT",         # 跨来源规范化 URL 键（canonical.canonical_url_key）
    "first_seen_at": "TEXT",         # 首次采集时间（兼容旧行：回填 collected_at）
    "last_seen_at": "TEXT",          # 最近一次仍观测到的时间
    "link_status": "TEXT",           # active | expired | unknown
    "category": "TEXT",              # 归一分类（直采可空）
    "ai_category": "TEXT",           # 上游 AI 判定分类（可被 corrected_category 推翻）
    "corrected_category": "TEXT",    # 人工/规则纠错后的分类；非空即以此为准
}
V2_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_entries_external_key ON entries(external_key) WHERE external_key IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_entries_canonical ON entries(canonical_key)",
    "CREATE INDEX IF NOT EXISTS idx_entries_origin ON entries(origin_source)",
]

# ---- Schema v3 增量迁移（2026-11-17，生命周期管理）----
# 仍然只做 ADD COLUMN + 新表，不改列类型、不删列、不重建已有表。
V3_COLUMNS = {
    "value_score": "REAL",           # 动态价值分 0-100
    "value_tier": "TEXT",            # P0 永久 | P1 长期 | P2 标准 | P3 低值
    "score_updated_at": "TEXT",      # 最近一次评分时间
    "is_pinned": "INTEGER DEFAULT 0",  # 人工收藏/置顶，1 = 永不自动删除
    "link_checked_at": "TEXT",       # 失效状态最近核验时间（观察期起点）
    "retention_until": "TEXT",       # 由策略计算出的最早可清理时间（仅展示/审计用）
}
V4_TABLES = """
-- 正文层：RSS/API 只给标题+摘要，正文必须单独回源抓取并落库。
-- 与 entries 一对一（entry_id 主键），失败也留行，便于重试与统计成功率。
CREATE TABLE IF NOT EXISTS article_bodies (
    entry_id     INTEGER PRIMARY KEY,
    url          TEXT NOT NULL,
    status       TEXT NOT NULL,          -- ok | http_error | blocked | too_short | not_html | error
    engine       TEXT,                   -- trafilatura | readability | builtin | (失败为 NULL)
    via          TEXT,                   -- http | impersonate | proxy | browser
    char_len     INTEGER DEFAULT 0,
    body         TEXT,
    http_status  INTEGER,
    error        TEXT,
    attempts     INTEGER DEFAULT 1,
    fetched_at   TEXT NOT NULL,
    FOREIGN KEY (entry_id) REFERENCES entries(entry_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_bodies_status ON article_bodies(status);
CREATE INDEX IF NOT EXISTS idx_bodies_fetched ON article_bodies(fetched_at);
"""
V3_TABLES = """
CREATE TABLE IF NOT EXISTS retention_policy (
    policy_key   TEXT PRIMARY KEY,
    scope        TEXT NOT NULL,          -- global | tier | category | source
    selector     TEXT,
    retain_days  INTEGER NOT NULL,
    action       TEXT NOT NULL,          -- keep | purge | downsample | observe
    description  TEXT,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS purge_log (
    purge_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER,
    table_name   TEXT NOT NULL,
    entry_id     INTEGER,
    reason       TEXT,
    value_score  REAL,
    value_tier   TEXT,
    row_json     TEXT NOT NULL,
    purged_at    TEXT NOT NULL,
    restored_at  TEXT,
    bytes        INTEGER
);
CREATE TABLE IF NOT EXISTS job_runs (
    run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name     TEXT NOT NULL,
    mode         TEXT NOT NULL,          -- dry-run | apply
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    collected    INTEGER DEFAULT 0,
    inserted     INTEGER DEFAULT 0,
    deduped      INTEGER DEFAULT 0,
    failed       INTEGER DEFAULT 0,
    purged       INTEGER DEFAULT 0,
    bytes_freed  INTEGER DEFAULT 0,
    status       TEXT DEFAULT 'running', -- running | PASS | PARTIAL | FAIL
    detail_json  TEXT
);
CREATE TABLE IF NOT EXISTS task_registry (
    task_key      TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    schedule      TEXT,
    script_path   TEXT,
    args          TEXT,
    skill_version TEXT,
    last_run_at   TEXT,
    last_status   TEXT,
    registered_at TEXT,
    config_hash   TEXT
);
CREATE INDEX IF NOT EXISTS idx_entries_value_tier ON entries(value_tier);
CREATE INDEX IF NOT EXISTS idx_entries_last_seen ON entries(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_purge_log_run ON purge_log(run_id);
CREATE INDEX IF NOT EXISTS idx_job_runs_job ON job_runs(job_name, started_at);
"""


def parse_ts(value: Any) -> datetime | None:
    """兼容 'Z' 结尾、无时区、仅日期三种历史格式。"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(str(value)[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


class IntelDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self._migrate_v2()
        self._migrate_v3()
        self._migrate_v4()
        self.conn.commit()

    def _migrate_v2(self) -> None:
        """Schema v1→v2：ADD COLUMN + 索引 + 旧行回填，全程幂等。"""
        c = self.conn
        existing = {row["name"] for row in c.execute("PRAGMA table_info(entries)")}
        for col, decl in V2_COLUMNS.items():
            if col not in existing:
                c.execute(f"ALTER TABLE entries ADD COLUMN {col} {decl}")
        for ddl in V2_INDEXES:
            c.execute(ddl)
        # 旧行回填：首/末见时间取 collected_at；链接状态 unknown；规范化键按现存 URL 补算
        from .canonical import canonical_url_key
        rows = c.execute(
            "SELECT entry_id, url, collected_at FROM entries "
            "WHERE first_seen_at IS NULL OR last_seen_at IS NULL OR link_status IS NULL "
            "OR canonical_key IS NULL"
        ).fetchall()
        for row in rows:
            c.execute(
                "UPDATE entries SET first_seen_at=COALESCE(first_seen_at, ?), "
                "last_seen_at=COALESCE(last_seen_at, ?), link_status=COALESCE(link_status, 'unknown'), "
                "canonical_key=COALESCE(canonical_key, ?) WHERE entry_id=?",
                (row["collected_at"], row["collected_at"], canonical_url_key(row["url"]), row["entry_id"]),
            )
        c.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        c.execute("INSERT OR IGNORE INTO schema_meta(key,value) VALUES('schema_version','v2')")

    def _migrate_v3(self) -> None:
        """Schema v2→v3：生命周期管理。ADD COLUMN + 新表，幂等，不触碰已有数据。"""
        c = self.conn
        existing = {row["name"] for row in c.execute("PRAGMA table_info(entries)")}
        for col, decl in V3_COLUMNS.items():
            if col not in existing:
                c.execute(f"ALTER TABLE entries ADD COLUMN {col} {decl}")
        c.executescript(V3_TABLES)
        c.execute("UPDATE schema_meta SET value='v3' WHERE key='schema_version'")
        c.execute("INSERT OR IGNORE INTO schema_meta(key,value) VALUES('schema_version','v3')")

    def _migrate_v4(self) -> None:
        """Schema v3→v4：正文层。只建新表，不动已有列与数据，幂等。"""
        c = self.conn
        c.executescript(V4_TABLES)
        c.execute("UPDATE schema_meta SET value='v4' WHERE key='schema_version'")
        c.execute("INSERT OR IGNORE INTO schema_meta(key,value) VALUES('schema_version','v4')")

    def close(self) -> None:
        self.conn.close()

    # ---------------- FTS 索引联动（可选，失败不影响主流程） ----------------
    def _fts_index_entry(self, entry_id: int, commit: bool = False) -> bool:
        """把条目同步进 FTS 索引；FTS5 不可用时静默跳过（检索会自动降级 LIKE）。

        commit=False 时由调用方在同一事务内提交，保证"主表写入 + 索引写入"原子性。
        """
        if getattr(self, "_fts_ok", None) is None:
            try:
                from .search import ensure_fts
                self._fts_ok = ensure_fts(self.conn)
            except Exception:
                self._fts_ok = False
        if not self._fts_ok:
            return False
        try:
            from .search import index_entry
            row = self.conn.execute("SELECT * FROM entries WHERE entry_id=?", (entry_id,)).fetchone()
            if row is not None:
                index_entry(self.conn, row)
                if commit:
                    self.conn.commit()
            return True
        except Exception:
            return False

    def __enter__(self) -> "IntelDB":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def upsert_source(self, name: str, kind: str, base_url: str | None = None,
                      auth_state: str = "unknown", note: str | None = None) -> int:
        with self.tx() as c:
            c.execute(
                "INSERT INTO sources(name,kind,base_url,auth_state,note) VALUES(?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, base_url=excluded.base_url, "
                "auth_state=excluded.auth_state, note=excluded.note",
                (name, kind, base_url, auth_state, note),
            )
            row = c.execute("SELECT source_id FROM sources WHERE name=?", (name,)).fetchone()
            return int(row["source_id"])

    def add_entry(self, source_name: str, source_kind: str, url: str, title: str | None,
                  author: str | None = None, published_at: str | None = None,
                  summary: str | None = None, metrics: dict | None = None,
                  extra: dict | None = None, origin_source: str | None = None,
                  aggregator: str | None = None, tags: list[str] | None = None,
                  external_key: str | None = None, category: str | None = None) -> str:
        """返回 inserted | duplicate。直采行同样写 canonical_key，供跨来源关联。"""
        from .canonical import canonical_url_key
        source_id = self.upsert_source(source_name, source_kind)
        digest = content_hash_for(url, title)
        now = datetime.now().isoformat(timespec="seconds")
        with self.tx() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO entries(source_id,url,title,author,published_at,collected_at,"
                "summary,content_hash,metrics_json,extra_json,canonical_key,first_seen_at,last_seen_at,"
                "link_status,origin_source,aggregator,external_key,category) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (source_id, url, title, author, published_at, now, summary, digest,
                 json.dumps(metrics or {}, ensure_ascii=False),
                 json.dumps(extra or {}, ensure_ascii=False),
                 canonical_url_key(url), now, now, "unknown",
                 origin_source, aggregator, external_key,
                 (category or "").strip()[:60] or None),
            )
        if cur.rowcount:
            self._fts_index_entry(int(cur.lastrowid), commit=True)
            if tags:
                self.add_tags(int(cur.lastrowid), tags)
        return "inserted" if cur.rowcount else "duplicate"

    def upsert_aggregated_entry(self, *, external_key: str, aggregator: str, origin_source: str,
                                url: str, title: str | None, author: str | None,
                                published_at: str | None, summary: str | None,
                                content: str | None, category: str | None, ai_category: str | None,
                                link_status: str, first_seen_at: str | None,
                                last_seen_at: str | None, metrics: dict, extra: dict) -> str:
        """聚合源条目幂等写入。返回 inserted | updated。

        - external_key 唯一：同一聚合条目重复采集只更新观测字段，绝不新增重复行。
        - content_hash 仍按 (url,title) 计算，与直采表保持同一去重语义。
        - 原始链接、上游源、首/末见时间、失效状态全部留痕。
        """
        from .canonical import canonical_url_key
        source_id = self.upsert_source(
            f"{aggregator}", "aggregator",
            base_url=f"https://{aggregator}/", auth_state="ok",
            note=f"二级聚合源；上游 origin_source 逐条保留，如 {origin_source}",
        )
        digest = content_hash_for(url, title)
        now = datetime.now().isoformat(timespec="seconds")
        merged_extra = dict(extra or {})
        if content:
            merged_extra["content"] = content
        with self.tx() as c:
            existing = c.execute(
                "SELECT entry_id FROM entries WHERE external_key=?", (external_key,)
            ).fetchone()
            if existing:
                c.execute(
                    "UPDATE entries SET url=?, title=?, author=?, published_at=?, summary=?, "
                    "metrics_json=?, extra_json=?, origin_source=?, canonical_key=?, "
                    "last_seen_at=?, link_status=?, category=COALESCE(corrected_category, category, ?), "
                    "ai_category=? WHERE entry_id=?",
                    (url, title, author, published_at, summary,
                     json.dumps(metrics, ensure_ascii=False),
                     json.dumps(merged_extra, ensure_ascii=False),
                     origin_source, canonical_url_key(url),
                     last_seen_at or now, link_status or "unknown",
                     category, ai_category, existing["entry_id"]),
                )
                self._fts_index_entry(int(existing["entry_id"]))
                return "updated"
            try:
                with self.tx() as c:
                    cur = c.execute(
                        "INSERT INTO entries(source_id,url,title,author,published_at,collected_at,summary,"
                        "content_hash,metrics_json,extra_json,external_key,origin_source,aggregator,"
                        "canonical_key,first_seen_at,last_seen_at,link_status,category,ai_category) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (source_id, url, title, author, published_at, now, summary, digest,
                         json.dumps(metrics, ensure_ascii=False),
                         json.dumps(merged_extra, ensure_ascii=False),
                         external_key, origin_source, aggregator, canonical_url_key(url),
                         first_seen_at or now, last_seen_at or now,
                         link_status or "unknown", category, ai_category),
                    )
                self._fts_index_entry(int(cur.lastrowid))
                return "inserted"
            except sqlite3.IntegrityError:
                # 同一 (url,title) 已由其他采集路径写入（历史行可能没有 external_key）：
                # 按 content_hash 归并到既有行，补齐 external_key 与观测字段，不新增重复行。
                with self.tx() as c:
                    row = c.execute("SELECT entry_id FROM entries WHERE content_hash=?",
                                    (digest,)).fetchone()
                    if row is None:
                        raise
                    c.execute(
                        "UPDATE entries SET external_key=COALESCE(external_key,?), origin_source=?, "
                        "aggregator=COALESCE(aggregator,?), last_seen_at=?, "
                        "link_status=COALESCE(link_status,'unknown'), "
                        "metrics_json=?, extra_json=? WHERE entry_id=?",
                        (external_key, origin_source, aggregator, last_seen_at or now,
                         json.dumps(metrics, ensure_ascii=False),
                         json.dumps(merged_extra, ensure_ascii=False), row["entry_id"]))
                self._fts_index_entry(int(row["entry_id"]), commit=True)
                return "updated"

    def find_canonical_group(self, url: str) -> list[dict]:
        """按规范化键找跨来源同主题条目（含直采与各聚合源）。"""
        from .canonical import canonical_url_key
        key = canonical_url_key(url)
        rows = self.conn.execute(
            "SELECT e.entry_id, e.url, e.title, e.origin_source, e.aggregator, e.link_status, "
            "s.name AS source_name FROM entries e LEFT JOIN sources s ON s.source_id=e.source_id "
            "WHERE e.canonical_key=? ORDER BY e.first_seen_at",
            (key,),
        ).fetchall()
        return [dict(r) for r in rows]

    def canonical_groups(self, min_size: int = 2) -> list[dict]:
        """列出被多个渠道/条目共同覆盖的规范化主题（跨源关联证据）。"""
        rows = self.conn.execute(
            "SELECT canonical_key, COUNT(*) AS n, "
            "GROUP_CONCAT(DISTINCT COALESCE(aggregator, origin_source, 'direct')) AS channels "
            "FROM entries WHERE canonical_key IS NOT NULL AND canonical_key<>'' "
            "GROUP BY canonical_key HAVING n>=? ORDER BY n DESC",
            (min_size,),
        ).fetchall()
        return [dict(r) for r in rows]

    def correct_category(self, entry_id: int, corrected: str) -> None:
        """AI 分类纠错：写 corrected_category，不覆盖原始 ai_category（可审计）。"""
        with self.tx() as c:
            c.execute("UPDATE entries SET corrected_category=? WHERE entry_id=?",
                      (corrected, entry_id))

    def mark_link_status(self, entry_id: int, status: str) -> None:
        """失效链接人工/规则标记：active | expired | unknown。"""
        with self.tx() as c:
            c.execute("UPDATE entries SET link_status=? WHERE entry_id=?", (status, entry_id))

    def mark_read(self, url: str, state: str) -> int:
        with self.tx() as c:
            cur = c.execute("UPDATE entries SET read_state=? WHERE url=?", (state, url))
            return cur.rowcount

    # ---------------- v5：按需深度阅读（内容存储 + 状态推进 + 处理日志） ----------------
    READ_LOG_SCHEMA = """
    CREATE TABLE IF NOT EXISTS read_log (
        log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_id      INTEGER,
        stage         TEXT NOT NULL,          -- fetch | read | analyze
        status        TEXT NOT NULL,          -- SUCCESS | FAILED | SKIPPED
        http_status   INTEGER,
        bytes         INTEGER,
        content_chars INTEGER,
        error         TEXT,
        at            TEXT NOT NULL
    );
    """

    def ensure_read_log(self) -> None:
        self.conn.executescript(self.READ_LOG_SCHEMA)
        self.conn.commit()

    def log_read(self, entry_id: int, stage: str, status: str, *, http_status: int | None = None,
                 nbytes: int = 0, content_chars: int = 0, error: str | None = None) -> int:
        self.ensure_read_log()
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO read_log(entry_id,stage,status,http_status,bytes,content_chars,error,at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (entry_id, stage, status, http_status, nbytes, content_chars,
                 (error or "")[:400], datetime.now().isoformat(timespec="seconds")))
            return int(cur.lastrowid)

    def store_content(self, entry_id: int, content: str) -> bool:
        """把抓取到的正文写入 extra_json.content 并同步 FTS 索引。"""
        import json as _json
        row = self.conn.execute("SELECT extra_json FROM entries WHERE entry_id=?",
                                (entry_id,)).fetchone()
        if row is None:
            return False
        try:
            extra = _json.loads(row["extra_json"]) if row["extra_json"] else {}
        except _json.JSONDecodeError:
            extra = {}
        if not isinstance(extra, dict):
            extra = {}
        extra["content"] = content[:20000]
        with self.tx() as c:
            c.execute("UPDATE entries SET extra_json=?, last_seen_at=? WHERE entry_id=?",
                      (_json.dumps(extra, ensure_ascii=False),
                       datetime.now().isoformat(timespec="seconds"), entry_id))
        self._fts_index_entry(int(entry_id), commit=True)
        return True

    def mark_read_state_by_id(self, entry_id: int, state: str) -> str:
        """按状态机推进（只前进）；返回最终状态。"""
        if state not in self.READ_STATES:
            raise ValueError(f"非法 read_state {state!r}")
        row = self.conn.execute("SELECT read_state FROM entries WHERE entry_id=?",
                                (entry_id,)).fetchone()
        if row is None:
            return "not_found"
        cur = row["read_state"] or "title_scanned"
        if cur not in self.READ_STATES:
            cur = "title_scanned"
        if self.READ_STATES.index(state) <= self.READ_STATES.index(cur):
            return cur
        with self.tx() as c:
            c.execute("UPDATE entries SET read_state=? WHERE entry_id=?", (state, entry_id))
        return state

    def get_entry(self, entry_id: int) -> dict | None:
        self.conn.row_factory = sqlite3.Row
        row = self.conn.execute("SELECT * FROM entries WHERE entry_id=?", (entry_id,)).fetchone()
        return dict(row) if row else None

    def add_insight(self, project_name: str, claim: str, evidence: list[dict],
                    confidence: str = "medium") -> int:
        with self.tx() as c:
            c.execute(
                "INSERT OR IGNORE INTO projects(name,created_at) VALUES(?,?)",
                (project_name, datetime.now().isoformat(timespec="seconds")),
            )
            pid = c.execute("SELECT project_id FROM projects WHERE name=?", (project_name,)).fetchone()["project_id"]
            cur = c.execute(
                "INSERT INTO insights(project_id,created_at,claim,evidence_json,confidence) VALUES(?,?,?,?,?)",
                (pid, datetime.now().isoformat(timespec="seconds"), claim,
                 json.dumps(evidence, ensure_ascii=False), confidence),
            )
            return int(cur.lastrowid)

    def start_run(self, question: str) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO analysis_runs(started_at,question,status) VALUES(?,?, 'running')",
                (datetime.now().isoformat(timespec="seconds"), question),
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, coverage: dict, status: str = "done") -> None:
        with self.tx() as c:
            c.execute(
                "UPDATE analysis_runs SET finished_at=?, coverage_json=?, status=? WHERE run_id=?",
                (datetime.now().isoformat(timespec="seconds"),
                 json.dumps(coverage, ensure_ascii=False), status, run_id),
            )

    def stats(self) -> dict[str, int]:
        c = self.conn
        return {
            "sources": c.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "entries": c.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            "insights": c.execute("SELECT COUNT(*) FROM insights").fetchone()[0],
            "runs": c.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0],
        }

    # ---------------- v4：读取状态机 / 标签 / 关联（增量追加，不改旧方法语义） ----------------
    READ_STATES = ["title_scanned", "content_fetched", "content_read", "analyzed", "archived"]

    def mark_read_state(self, url: str, state: str) -> str:
        """按状态机推进读取状态：只能前进，不允许把已 analyzed 改回 title_scanned。

        返回推进后的状态；若状态非法或试图降级，返回当前状态且不写入。
        """
        if state not in self.READ_STATES:
            raise ValueError(f"非法 read_state {state!r}，允许：{self.READ_STATES}")
        with self.tx() as c:
            row = c.execute("SELECT entry_id, read_state FROM entries WHERE url=?", (url,)).fetchone()
            if row is None:
                return "not_found"
            cur = row["read_state"] or "title_scanned"
            if cur not in self.READ_STATES:
                cur = "title_scanned"
            if self.READ_STATES.index(state) <= self.READ_STATES.index(cur):
                return cur
            c.execute("UPDATE entries SET read_state=? WHERE entry_id=?", (state, row["entry_id"]))
            return state

    def add_tags(self, entry_id: int, tags: list[str]) -> int:
        """给条目打标签（真实标签，不生成虚假标签）。返回新增标签数。"""
        added = 0
        with self.tx() as c:
            for raw in tags:
                name = (raw or "").strip().lower()
                if not name:
                    continue
                c.execute("INSERT OR IGNORE INTO tags(name) VALUES(?)", (name,))
                tid = c.execute("SELECT tag_id FROM tags WHERE name=?", (name,)).fetchone()[0]
                cur = c.execute(
                    "INSERT OR IGNORE INTO entry_tags(entry_id, tag_id) VALUES(?,?)", (entry_id, tid))
                added += cur.rowcount
        return added

    def list_tags(self, entry_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT t.name FROM tags t JOIN entry_tags et ON et.tag_id=t.tag_id "
            "WHERE et.entry_id=? ORDER BY t.name", (entry_id,)).fetchall()
        return [r[0] for r in rows]

    def link_relation(self, from_entry: int, to_entry: int, relation: str, note: str | None = None) -> int:
        """登记显式技术关联（combo / extends / contradicts / same-subject），不伪造关联。"""
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO relations(from_entry,to_entry,relation,note) VALUES(?,?,?,?)",
                (from_entry, to_entry, relation, note))
            return int(cur.lastrowid)

    def related_entries(self, entry_id: int) -> list[dict]:
        """显式关系 + 同 canonical_key 的隐式同主题条目。"""
        rows = self.conn.execute(
            "SELECT e.entry_id, e.title, e.url, r.relation, r.note FROM relations r "
            "JOIN entries e ON e.entry_id = CASE WHEN r.from_entry=? THEN r.to_entry ELSE r.from_entry END "
            "WHERE r.from_entry=? OR r.to_entry=?", (entry_id, entry_id, entry_id)).fetchall()
        out = [dict(r) for r in rows]
        key = self.conn.execute(
            "SELECT canonical_key FROM entries WHERE entry_id=?", (entry_id,)).fetchone()
        if key and key[0]:
            for r in self.conn.execute(
                    "SELECT entry_id, title, url FROM entries WHERE canonical_key=? AND entry_id<>?",
                    (key[0], entry_id)).fetchall():
                out.append({"entry_id": r[0], "title": r[1], "url": r[2],
                            "relation": "same-subject", "note": key[0]})
        return out
