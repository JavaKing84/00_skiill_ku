"""统一采集管线：解析 → 标准化 → 质量校验 → 去重 → 入库 → FTS 索引。

两个通道（A 公开 / B 认证）都走这一条管线，产出同一套 entries 结构，保证可统一检索。
故障隔离：每个来源独立执行，异常被捕获为该来源的失败状态，不影响其他来源与调度器。
"""
from __future__ import annotations

import re
import sqlite3
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .http import FetchError
from .loggingx import mask
from .sources import set_status, upsert_source

MAX_TITLE = 400
MAX_SUMMARY = 4000
MAX_CONTENT = 20000


@dataclass
class Record:
    url: str
    title: str
    published_at: str | None = None
    summary: str | None = None
    content: str | None = None
    author: str | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    external_key: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class SourceSpec:
    source_id: str
    source_name: str
    source_type: str            # api | rss | atom | html
    channel: str                # public | authenticated
    fetch: Callable[[], list[Record]]
    auth_required: bool = False
    authorization_status: str = "not_required"
    credential_status: str = "not_required"
    aggregator: str | None = None
    origin_extra_key: str | None = None   # 聚合源：真实上游来源在 extra 里的键名
    enabled: bool = True


def _clean(text: Any) -> str:
    if text is None:
        return ""
    s = re.sub(r"[ \t\r\f\v]+", " ", str(text))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize(raw: Record, source_id: str) -> Record | None:
    """标准化 + 质量校验：缺 URL 或标题直接丢弃（不编造）。"""
    url = (raw.url or "").strip()
    title = _clean(raw.title)
    if not url.startswith(("http://", "https://")) or not title:
        return None
    summary = _clean(raw.summary)[:MAX_SUMMARY] or None
    content = _clean(raw.content)[:MAX_CONTENT] or None
    if not summary and content:
        summary = content[:500]
    return Record(
        url=url, title=title[:MAX_TITLE], published_at=raw.published_at,
        summary=summary, content=content,
        author=_clean(raw.author)[:200] or None,
        category=(raw.category or "").strip()[:60] or None,
        tags=[t.strip().lower() for t in raw.tags if t and t.strip()][:12],
        metrics=raw.metrics or {},
        external_key=raw.external_key or f"{source_id}:{url}",
        extra=raw.extra or {},
    )


def ingest(db, records: list[Record], source_id: str, source_kind: str,
           aggregator: str | None = None, origin_extra_key: str | None = None,
           require_provenance: bool = True) -> dict:
    """去重 + 入库（自动写 canonical_key 与 FTS 索引）。

    origin_extra_key：聚合源的"真实上游"字段（如同一条目来自哪个社区/feed），
    写入 origin_source，避免把聚合渠道本身当成上游来源。
    require_provenance：入库前校验 URL 与 origin_source；不通过则进隔离区、不入库。
    """
    from .provenance import quarantine, validate

    inserted = deduped = skipped = quarantined = 0
    for raw in records:
        rec = normalize(raw, source_id)
        if rec is None:
            # 连规范化都过不了（无 URL / 无标题）→ 进隔离区，不静默丢弃
            quarantine(db.conn, source_id=source_id, reason="normalize_failed",
                       url=getattr(raw, "url", None), title=getattr(raw, "title", None),
                       payload={"url": getattr(raw, "url", None),
                                "title": getattr(raw, "title", None),
                                "aggregator": aggregator})
            quarantined += 1
            continue
        origin = source_id
        if origin_extra_key:
            origin = str(rec.extra.get(origin_extra_key) or source_id)
        if require_provenance:
            ok, reason = validate(rec.url, origin, aggregator)
            if not ok:
                quarantine(db.conn, source_id=source_id, reason=reason, url=rec.url,
                           title=rec.title,
                           payload={"url": rec.url, "title": rec.title, "origin": origin,
                                    "aggregator": aggregator, "extra": rec.extra})
                quarantined += 1
                continue
        verdict = db.add_entry(
            source_name=source_id, source_kind=source_kind, url=rec.url, title=rec.title,
            author=rec.author, published_at=rec.published_at, summary=rec.summary,
            metrics=rec.metrics,
            extra={**rec.extra, **({"content": rec.content} if rec.content else {})},
            origin_source=origin, aggregator=aggregator, tags=rec.tags,
            external_key=rec.external_key, category=rec.category)
        if verdict == "inserted":
            inserted += 1
        else:
            deduped += 1
    return {"inserted": inserted, "deduped": deduped, "skipped": skipped,
            "quarantined": quarantined}


def run_source(db, conn: sqlite3.Connection, spec: SourceSpec) -> dict:
    """执行一个来源并记录状态；任何异常都被隔离在本来源内。"""
    upsert_source(conn, spec.source_id, spec.source_name, spec.source_type, spec.channel,
                  auth_required=spec.auth_required,
                  authorization_status=spec.authorization_status,
                  credential_status=spec.credential_status,
                  status="READY" if spec.enabled else "DISABLED",
                  enabled=spec.enabled)
    if not spec.enabled:
        set_status(conn, spec.source_id, "DISABLED", attempted=False, collection_status="NEVER_RUN")
        return {"source_id": spec.source_id, "status": "DISABLED", "fetched": 0,
                "inserted": 0, "deduped": 0, "quarantined": 0, "error": None}
    try:
        records = spec.fetch()
        stats = ingest(db, records, spec.source_id, spec.source_type, spec.aggregator,
                       spec.origin_extra_key)
        set_status(conn, spec.source_id, "READY", fetched=stats["inserted"] + stats["deduped"],
                   inserted=stats["inserted"], deduped=stats["deduped"], succeeded=True,
                   connectivity_status="ONLINE", collection_status="SUCCESS",
                   configuration_status="CONFIGURED", last_error="")
        return {"source_id": spec.source_id, "status": "READY",
                "fetched": stats["inserted"] + stats["deduped"],
                "inserted": stats["inserted"], "deduped": stats["deduped"],
                "quarantined": stats["quarantined"], "error": None}
    except FetchError as exc:
        status = {"auth": "AUTH_REQUIRED", "approval": "APPROVAL_REQUIRED",
                  "rate_limit": "DEGRADED", "network": "DEGRADED",
                  "http": "DEGRADED", "parse": "DEGRADED"}.get(exc.kind, "DEGRADED")
        conn_kind = {"auth": "BLOCKED", "approval": "BLOCKED",
                     "rate_limit": "OFFLINE", "network": "OFFLINE",
                     "http": "OFFLINE", "parse": "UNKNOWN"}.get(exc.kind, "UNKNOWN")
        collection = "BLOCKED" if exc.kind in ("auth", "approval") else "FAILED"
        set_status(conn, spec.source_id, status, last_error=str(exc), succeeded=False,
                   authorization_status=("pending" if exc.kind == "approval" else None),
                   credential_status=("invalid" if exc.kind == "auth" else None),
                   connectivity_status=conn_kind, collection_status=collection)
        return {"source_id": spec.source_id, "status": status, "fetched": 0, "inserted": 0,
                "deduped": 0, "quarantined": 0, "error": mask(str(exc))[:300]}
    except Exception as exc:  # 兜底：任何异常都不应中断调度
        detail = mask(f"{type(exc).__name__}: {exc}")
        set_status(conn, spec.source_id, "DEGRADED", last_error=detail, succeeded=False,
                   connectivity_status="UNKNOWN", collection_status="FAILED")
        return {"source_id": spec.source_id, "status": "DEGRADED", "fetched": 0, "inserted": 0,
                "deduped": 0, "quarantined": 0, "error": detail[:300]}


def run_sources(db, conn: sqlite3.Connection, specs: list[SourceSpec]) -> list[dict]:
    """依次执行多个来源；单个来源失败不影响其余来源。"""
    results = []
    for spec in specs:
        try:
            results.append(run_source(db, conn, spec))
        except Exception as exc:  # 双保险
            results.append({"source_id": spec.source_id, "status": "DEGRADED", "fetched": 0,
                            "inserted": 0, "deduped": 0,
                            "error": mask(f"{type(exc).__name__}: {exc}")[:300]})
    return results
