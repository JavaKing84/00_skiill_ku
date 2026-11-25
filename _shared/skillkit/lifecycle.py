"""情报生命周期引擎：动态价值评分 + 保留策略 + 安全清理 + 恢复。

设计约束：
- 只操作既有 entries/snapshots/insights 表，新增 retention_policy / purge_log / job_runs / task_registry。
- 删除前由调用方完成数据库备份；本模块负责把整行 JSON 写入 purge_log，之后才 DELETE。
- 受保护数据（人工收藏、深度阅读、洞察引用、高价值）任何策略都不会删。
- 所有函数只接收 sqlite3.Connection，便于在临时库上做真实删除/恢复测试。
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from .inteldb import parse_ts

# ---------------------------------------------------------------- 默认策略
# 写进 Skill 与 retention_policy 表，Agent 更新时可对照同步。
DEFAULT_CONFIG: dict[str, Any] = {
    "version": "1.0.0",
    "skill_version": "1.2.0",
    "apply_purge": False,          # 总开关：false = 永远 dry-run，绝不真删
    "observation_days": 14,        # 失效链接观察期
    "snapshots": {"raw_days": 90, "daily_keep_days": 400},
    "retention_days": {
        "default": 180,            # 普通帖子正文
        "reddit_comment": 90,      # Reddit 评论
        "github": 3650,            # GitHub 项目资料：长期保留并定期更新
        "perm": 36500,             # 永久档（10 年，视为永久）
        "low_value": 30,           # 泛低值
        "promo_goods": 7,          # 交易/优惠/邀请码类推广
        "promo_other": 14,
        "snapshot": 90,
    },
    "low_value_categories": ["goods", "trade", "invite", "carpool", "other", "noise"],
    "perm_tiers": ["P0"],
    "project_profiles": {
        "ai-robot": ["robot", "robotics", "vla", "embodied", "具身", "机器人", "sim2real",
                     "manipulation", "机械臂", "navigation", "多模态感知", "仿真"],
        "small-model": ["fine-tun", "finetune", "lora", "qlora", "distill", "quantiz", "gguf",
                        "llama.cpp", "mlx", "微调", "量化", "蒸馏", "小模型", "sft", "dpo"],
        "douyin-growth": ["ffmpeg", "剪辑", "字幕", "配音", "短视频", "remotion", "自动化",
                          "内容运营", "素材", "口播", "cover", "caption"],
        "ai-agent": ["agent", "multi-agent", "mcp", "workflow", "tool-use", "rag", "智能体"],
    },
    "value_weights": {
        "novelty": 30, "quality": 20, "community": 15,
        "maintenance": 10, "cross_source": 10, "relevance": 15,
    },
    "tier_thresholds": {"P0": 85, "P1": 65, "P2": 40},
}

TIER_LABEL = {"P0": "永久", "P1": "长期", "P2": "标准", "P3": "低值"}


@dataclass
class PurgeCandidate:
    entry_id: int
    title: str | None
    url: str
    tier: str
    score: float
    reason: str
    retain_days: int
    age_days: float
    bytes: int
    row: dict = field(default_factory=dict)


def _json_load(raw: str | None) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def load_config(path) -> dict:
    from pathlib import Path
    p = Path(path)
    if p.exists():
        cfg = json.loads(p.read_text(encoding="utf-8"))
        merged = json.loads(json.dumps(DEFAULT_CONFIG))
        for k, v in cfg.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k].update(v)
            else:
                merged[k] = v
        return merged
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(path, cfg: dict) -> None:
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def sync_policy_table(conn: sqlite3.Connection, cfg: dict) -> int:
    """把配置写进 retention_policy 表，供审计与跨客户端读取。"""
    now = datetime.now().isoformat(timespec="seconds")
    rows: list[tuple] = []
    rd = cfg["retention_days"]
    rows.append(("global.default", "global", "*", rd["default"], "purge", "普通帖子正文默认 180 天"))
    rows.append(("source.reddit_comment", "source", "reddit_comment", rd["reddit_comment"], "purge", "Reddit 评论 90 天"))
    rows.append(("source.github", "source", "github", rd["github"], "keep", "GitHub 项目资料长期保留并定期更新"))
    rows.append(("tier.P0", "tier", "P0", rd["perm"], "keep", "技术洞察/高价值/人工收藏永久保留"))
    rows.append(("tier.P1", "tier", "P1", rd["github"], "keep", "长期档案 10 年"))
    rows.append(("tier.P2", "tier", "P2", rd["default"], "purge", "标准正文 180 天"))
    rows.append(("tier.P3", "tier", "P3", rd["low_value"], "purge", "低价值 7-30 天"))
    for cat in cfg["low_value_categories"]:
        days = rd["promo_goods"] if cat in {"goods", "trade", "invite", "carpool"} else rd["promo_other"]
        rows.append((f"category.{cat}", "category", cat, days, "purge", f"{cat} 类低值内容 {days} 天"))
    rows.append(("snapshots.raw", "global", "snapshots", cfg["snapshots"]["raw_days"], "downsample", "热度快照 90 天后降采样"))
    for r in rows:
        conn.execute(
            "INSERT INTO retention_policy(policy_key,scope,selector,retain_days,action,description,updated_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(policy_key) DO UPDATE SET scope=excluded.scope, "
            "selector=excluded.selector, retain_days=excluded.retain_days, action=excluded.action, "
            "description=excluded.description, updated_at=excluded.updated_at",
            (*r, now),
        )
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------- 价值评分
def _protected_ids(conn: sqlite3.Connection) -> set[int]:
    """人工收藏 + 洞察证据引用。"""
    ids: set[int] = set()
    for row in conn.execute("SELECT entry_id FROM entries WHERE COALESCE(is_pinned,0)=1"):
        ids.add(int(row[0]))
    try:
        for row in conn.execute("SELECT evidence_json FROM insights"):
            for ev in _json_load_pairs(row[0]):
                eid = ev.get("entry_id")
                if isinstance(eid, int):
                    ids.add(eid)
    except sqlite3.Error:
        pass
    return ids


def _json_load_pairs(raw: str | None) -> list[dict]:
    try:
        data = json.loads(raw) if raw else []
        return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _relevance(text: str, profiles: dict[str, list[str]]) -> tuple[float, list[str]]:
    """用户项目相关性：命中几个不同项目即给几档分，避免单词堆叠刷分。"""
    low = text.lower()
    hit_projects, hit_terms = [], []
    for proj, kws in profiles.items():
        for kw in kws:
            if kw.lower() in low:
                if proj not in hit_projects:
                    hit_projects.append(proj)
                if kw not in hit_terms:
                    hit_terms.append(kw)
    if not hit_projects:
        return 0.0, []
    base = min(1.0, len(hit_projects) / 2) * 0.7 + min(1.0, len(hit_terms) / 4) * 0.3
    return base, hit_projects


def score_entry(row: dict, now: datetime, cfg: dict,
                cross_count: int = 1, protected: bool = False) -> dict:
    """返回 {score, tier, parts}。分数 0-100，可解释。"""
    w = cfg["value_weights"]
    metrics = _json_load(row.get("metrics_json"))
    extra = _json_load(row.get("extra_json"))
    base_dt = parse_ts(row.get("published_at")) or parse_ts(row.get("first_seen_at")) \
        or parse_ts(row.get("collected_at")) or now
    age_days = max(0.0, (now - base_dt).total_seconds() / 86400)

    # 新颖性：指数衰减，180 天约剩 22%
    novelty = w["novelty"] * math.exp(-age_days / 120.0)

    # 内在价值：上游 AI 质量优先，其次按形态
    quality_raw = metrics.get("ai_quality")
    kind = str(extra.get("kind") or row.get("kind") or "").lower()
    if isinstance(quality_raw, (int, float)):
        quality = w["quality"] * (float(quality_raw) / 5.0)
    else:
        kind_base = {"opensource": 0.8, "info": 0.65, "news": 0.55,
                     "deal": 0.3, "freebie": 0.2, "noise": 0.0}.get(kind, 0.5)
        quality = w["quality"] * kind_base
    if metrics.get("ai_keep") is True:
        quality = min(w["quality"], quality + 2)
    if metrics.get("ai_keep") is False:
        quality = max(0.0, quality - 6)

    # 社区讨论
    points = metrics.get("points") or metrics.get("stars") or metrics.get("score") or 0
    comments = metrics.get("comments") or 0
    try:
        community = min(w["community"], math.log1p(max(0, float(points))) * 2.2
                        + math.log1p(max(0, float(comments))) * 2.2)
    except (TypeError, ValueError):
        community = 0.0

    # 维护状态：最近仍被观测到 + 仓库活跃信号
    last_dt = parse_ts(row.get("last_seen_at")) or base_dt
    fresh_days = max(0.0, (now - last_dt).total_seconds() / 86400)
    maintenance = w["maintenance"] * max(0.0, 1.0 - fresh_days / 180.0)
    if row.get("origin_source") and "github" in str(row.get("origin_source")):
        maintenance = min(w["maintenance"], maintenance + 3)

    # 跨源复现
    cross = min(w["cross_source"], max(0, cross_count - 1) * 5.0)

    # 用户项目相关性
    text = " ".join(str(row.get(k) or "") for k in ("title", "summary", "extra_json", "category"))
    rel_ratio, hit_projects = _relevance(text, cfg["project_profiles"])
    relevance = w["relevance"] * rel_ratio

    # 惩罚：推广/失效
    penalty = 0.0
    if str(metrics.get("obtain") or "").lower() in {"promo"}:
        penalty += 8
    if row.get("link_status") == "expired":
        penalty -= 0  # 失效不直接砍分，交给观察期策略
    if str(row.get("category") or "") in cfg["low_value_categories"]:
        penalty += 4

    raw = novelty + quality + community + maintenance + cross + relevance - penalty
    score = round(max(0.0, min(100.0, raw)), 2)

    # 分档：除分数外，保留「耐久价值」硬规则，避免历史高价值项目因不再热门被降档
    try:
        points_val = float(metrics.get("points") or metrics.get("stars") or 0)
        stars_val = float(metrics.get("stars") or 0)
    except (TypeError, ValueError):
        points_val = stars_val = 0.0
    quality_val = float(quality_raw) if isinstance(quality_raw, (int, float)) else None
    github_like = _is_github(row)

    durable_p0 = (
        (quality_val is not None and quality_val >= 5)
        or points_val >= 1000
        or stars_val >= 3000
        or (metrics.get("ai_keep") is True and quality_val is not None and quality_val >= 4 and points_val >= 300)
    )
    strong = (quality_val is not None and quality_val >= 4) or points_val >= 200 or stars_val >= 500

    t = cfg["tier_thresholds"]
    if protected or int(row.get("is_pinned") or 0) == 1 or durable_p0 or score >= t["P0"]:
        tier = "P0"
    elif github_like or strong or score >= t["P1"]:
        tier = "P1"
    elif score >= t["P2"]:
        tier = "P2"
    else:
        tier = "P3"

    return {
        "score": score,
        "tier": tier,
        "parts": {
            "novelty": round(novelty, 2), "quality": round(quality, 2),
            "community": round(community, 2), "maintenance": round(maintenance, 2),
            "cross_source": round(cross, 2), "relevance": round(relevance, 2),
            "penalty": round(penalty, 2), "age_days": round(age_days, 1),
            "hit_projects": hit_projects,
        },
    }


def rescore_all(conn: sqlite3.Connection, cfg: dict, now: datetime | None = None) -> dict:
    """全库重算价值分与档位；人工收藏强制 P0。"""
    now = now or datetime.now()
    protected = _protected_ids(conn)
    cross_map = {
        row[0]: int(row[1]) for row in conn.execute(
            "SELECT canonical_key, COUNT(*) FROM entries WHERE canonical_key IS NOT NULL "
            "AND canonical_key<>'' GROUP BY canonical_key")
    }
    rows = conn.execute("SELECT * FROM entries").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM entries LIMIT 0").description]
    dist = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    changed = 0
    for r in rows:
        rec = dict(zip(cols, r))
        result = score_entry(rec, now, cfg,
                             cross_count=cross_map.get(rec.get("canonical_key"), 1),
                             protected=rec["entry_id"] in protected)
        if rec.get("value_tier") != result["tier"] or rec.get("value_score") != result["score"]:
            changed += 1
        conn.execute(
            "UPDATE entries SET value_score=?, value_tier=?, score_updated_at=?, "
            "is_pinned=COALESCE(is_pinned,0) WHERE entry_id=?",
            (result["score"], result["tier"], now.isoformat(timespec="seconds"), rec["entry_id"]),
        )
        dist[result["tier"]] += 1
    conn.commit()
    return {"scored": len(rows), "changed": changed, "distribution": dist,
            "protected": len(protected)}


# ---------------------------------------------------------------- 保留策略
def _is_github(row: dict) -> bool:
    """严格判断 GitHub 项目资料：仅认 github.com 链接或 github-* 上游源，避免 r/*github* 误判。"""
    url = str(row.get("url") or "").lower()
    origin = str(row.get("origin_source") or "").lower()
    source = str(row.get("source_name") or "").lower()
    if "github.com/" in url:
        return True
    if origin.startswith("github-") or origin.startswith("github."):
        return True
    if source.startswith("github") and "reddit" not in origin:
        return True
    return False


def _is_reddit(row: dict) -> bool:
    origin = str(row.get("origin_source") or "").lower()
    source = str(row.get("source_name") or "").lower()
    return origin.startswith("r/") or "reddit" in origin or "reddit" in source


def _retain_days(row: dict, cfg: dict) -> tuple[int, str]:
    """返回 (保留天数, 依据说明)。顺序：收藏/洞察 > Reddit > GitHub > 档位 > 分类。"""
    rd = cfg["retention_days"]
    if int(row.get("is_pinned") or 0) == 1:
        return rd["perm"], "人工收藏"
    category = str(row.get("corrected_category") or row.get("category") or "")
    if row.get("value_tier") == "P0":
        return rd["perm"], "P0 高价值/洞察"
    if _is_reddit(row):
        return rd["reddit_comment"], "Reddit 条目/评论 90 天"
    if _is_github(row):
        return rd["github"], "GitHub 项目资料长期保留"
    if row.get("value_tier") == "P1":
        return rd["github"], "P1 长期档案"
    if category in cfg["low_value_categories"]:
        days = rd["promo_goods"] if category in {"goods", "trade", "invite", "carpool"} else rd["promo_other"]
        return days, f"{category} 类低值内容"
    if row.get("value_tier") == "P3":
        return rd["low_value"], "P3 低值"
    return rd["default"], "普通正文 180 天"


def plan_purge(conn: sqlite3.Connection, cfg: dict, now: datetime | None = None) -> list[PurgeCandidate]:
    """只读规划：返回可清理候选，绝不删除。受保护数据永不入选。"""
    now = now or datetime.now()
    obs_days = int(cfg["observation_days"])
    protected = _protected_ids(conn)
    rows = conn.execute(
        "SELECT e.*, s.name AS source_name, s.kind AS source_kind FROM entries e "
        "LEFT JOIN sources s ON s.source_id=e.source_id"
    ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT e.*, s.name AS source_name, s.kind AS source_kind "
                                       "FROM entries e LEFT JOIN sources s ON s.source_id=e.source_id LIMIT 0").description]
    out: list[PurgeCandidate] = []
    for r in rows:
        rec = dict(zip(cols, r))
        eid = int(rec["entry_id"])
        if eid in protected:
            continue
        if rec.get("read_state") == "deep_read":
            continue  # 已深读视为已产生知识价值
        retain, reason = _retain_days(rec, cfg)
        last = parse_ts(rec.get("last_seen_at")) or parse_ts(rec.get("collected_at")) or now
        age = (now - last).total_seconds() / 86400
        # 失效链接观察期：expired 且未过观察期不删
        if rec.get("link_status") == "expired":
            checked = parse_ts(rec.get("link_checked_at")) or last
            if (now - checked).total_seconds() / 86400 < obs_days:
                continue
            reason += f"（已过 {obs_days} 天观察期）"
        if age <= retain:
            continue
        row_json = json.dumps(rec, ensure_ascii=False, default=str)
        out.append(PurgeCandidate(
            entry_id=eid, title=rec.get("title"), url=rec.get("url") or "",
            tier=rec.get("value_tier") or "P2", score=float(rec.get("value_score") or 0),
            reason=reason, retain_days=retain, age_days=round(age, 1),
            bytes=len(row_json.encode("utf-8")), row=rec,
        ))
    out.sort(key=lambda c: (c.score, -c.age_days))
    return out


def apply_purge(conn: sqlite3.Connection, candidates: Iterable[PurgeCandidate],
                run_id: int | None, now: datetime | None = None,
                batch_limit: int | None = None) -> dict:
    """先写 purge_log（整行 JSON）再删除；返回数量与估算空间。"""
    now = now or datetime.now()
    deleted = bytes_total = 0
    for c in candidates:
        if batch_limit is not None and deleted >= batch_limit:
            break
        row_json = json.dumps(c.row, ensure_ascii=False, default=str)
        conn.execute(
            "INSERT INTO purge_log(run_id,table_name,entry_id,reason,value_score,value_tier,"
            "row_json,purged_at,bytes) VALUES(?,?,?,?,?,?,?,?,?)",
            (run_id, "entries", c.entry_id, c.reason, c.score, c.tier,
             row_json, now.isoformat(timespec="seconds"), len(row_json.encode("utf-8"))),
        )
        conn.execute("DELETE FROM entry_tags WHERE entry_id=?", (c.entry_id,))
        conn.execute("DELETE FROM entries WHERE entry_id=?", (c.entry_id,))
        try:  # 同步清理 FTS 索引（FTS 不存在则忽略）
            conn.execute("DELETE FROM entries_fts WHERE entry_id=?", (c.entry_id,))
        except sqlite3.Error:
            pass
        deleted += 1
        bytes_total += len(row_json.encode("utf-8"))
    conn.commit()
    return {"deleted": deleted, "bytes": bytes_total}


def restore_purges(conn: sqlite3.Connection, purge_ids: list[int] | None = None,
                   run_id: int | None = None) -> dict:
    """从 purge_log 恢复整行；默认恢复全部未恢复记录（可指定 run_id）。"""
    if purge_ids:
        marks = ",".join("?" * len(purge_ids))
        rows = conn.execute(f"SELECT * FROM purge_log WHERE purge_id IN ({marks}) "
                            "AND restored_at IS NULL", purge_ids).fetchall()
    elif run_id is not None:
        rows = conn.execute("SELECT * FROM purge_log WHERE run_id=? AND restored_at IS NULL",
                            (run_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM purge_log WHERE restored_at IS NULL").fetchall()
    restored = skipped = 0
    for r in rows:
        rec = dict(r)
        if rec["table_name"] != "entries":
            skipped += 1
            continue
        data = json.loads(rec["row_json"])
        data.pop("source_name", None)
        data.pop("source_kind", None)
        cols = list(data.keys())
        exists = conn.execute("SELECT 1 FROM entries WHERE entry_id=?", (data["entry_id"],)).fetchone()
        if exists:
            skipped += 1
            continue
        conn.execute(
            f"INSERT INTO entries({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
            [data[c] for c in cols],
        )
        conn.execute("UPDATE purge_log SET restored_at=? WHERE purge_id=?",
                     (datetime.now().isoformat(timespec="seconds"), rec["purge_id"]))
        restored += 1
    conn.commit()
    return {"restored": restored, "skipped": skipped}


# ---------------------------------------------------------------- 快照降采样
def downsample_snapshots(conn: sqlite3.Connection, cfg: dict, run_id: int | None = None,
                         now: datetime | None = None, dry_run: bool = True) -> dict:
    """90 天内原样保留；90–400 天每天留 1 条；更早每周留 1 条；被删行写入 purge_log。"""
    now = now or datetime.now()
    raw_days = int(cfg["snapshots"]["raw_days"])
    daily_days = int(cfg["snapshots"]["daily_keep_days"])
    rows = conn.execute("SELECT * FROM snapshots ORDER BY entry_id, taken_at").fetchall()
    keep: set[int] = set()
    buckets: dict[tuple, int] = {}   # (entry, 粒度键) -> 保留 snapshot_id
    for r in rows:
        rec = dict(r)
        ts = parse_ts(rec.get("taken_at"))
        if not ts:
            continue
        age = (now - ts).total_seconds() / 86400
        if age <= raw_days:
            keep.add(rec["snapshot_id"])
            continue
        if age <= daily_days:
            key = (rec["entry_id"], ts.strftime("%Y-%m-%d"))
        else:
            iso = ts.isocalendar()
            key = (rec["entry_id"], f"{iso[0]}-W{iso[1]:02d}")
        prev = buckets.get(key)
        if prev is None:
            buckets[key] = rec["snapshot_id"]
            keep.add(rec["snapshot_id"])
        else:
            keep.discard(prev)
            buckets[key] = rec["snapshot_id"]
            keep.add(rec["snapshot_id"])
    to_delete = [dict(r) for r in rows if r["snapshot_id"] not in keep]
    if dry_run:
        return {"snapshots_total": len(rows), "keep": len(keep),
                "would_delete": len(to_delete), "dry_run": True}
    deleted = bytes_total = 0
    for rec in to_delete:
        row_json = json.dumps(rec, ensure_ascii=False, default=str)
        conn.execute(
            "INSERT INTO purge_log(run_id,table_name,entry_id,reason,value_score,value_tier,"
            "row_json,purged_at,bytes) VALUES(?,?,?,?,?,?,?,?,?)",
            (run_id, "snapshots", rec.get("entry_id"), "快照降采样", None, None,
             row_json, now.isoformat(timespec="seconds"), len(row_json.encode("utf-8"))),
        )
        conn.execute("DELETE FROM snapshots WHERE snapshot_id=?", (rec["snapshot_id"],))
        deleted += 1
        bytes_total += len(row_json.encode("utf-8"))
    conn.commit()
    return {"snapshots_total": len(rows), "keep": len(keep), "deleted": deleted,
            "bytes": bytes_total, "dry_run": False}


def capture_snapshots(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """为当天仍活跃的条目记录一次热度快照，供后续趋势与降采样使用。"""
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT entry_id, metrics_json FROM entries WHERE metrics_json IS NOT NULL "
        "AND metrics_json<>'{}' AND (value_tier IN ('P0','P1','P2') OR value_tier IS NULL)"
    ).fetchall()
    added = 0
    for eid, metrics in rows:
        exists = conn.execute(
            "SELECT 1 FROM snapshots WHERE entry_id=? AND substr(taken_at,1,10)=?", (eid, today)
        ).fetchone()
        if exists:
            continue
        conn.execute("INSERT INTO snapshots(entry_id,taken_at,metrics_json) VALUES(?,?,?)",
                     (eid, now.isoformat(timespec="seconds"), metrics))
        added += 1
    conn.commit()
    return added


# ---------------------------------------------------------------- 状态维护
def refresh_link_status(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """按 expires_at 更新失效状态并记录核验时间；不访问网络。"""
    now = now or datetime.now()
    updated = 0
    rows = conn.execute(
        "SELECT entry_id, extra_json, link_status FROM entries WHERE extra_json IS NOT NULL"
    ).fetchall()
    for eid, extra_raw, status in rows:
        exp = _json_load(extra_raw).get("expires_at")
        exp_dt = parse_ts(exp)
        if exp_dt and exp_dt < now and status != "expired":
            conn.execute("UPDATE entries SET link_status='expired', link_checked_at=? WHERE entry_id=?",
                         (now.isoformat(timespec="seconds"), eid))
            updated += 1
    conn.commit()
    return updated


def duplicate_report(conn: sqlite3.Connection) -> list[dict]:
    """同 canonical_key 下多个不同 content_hash，视为潜在重复。"""
    rows = conn.execute(
        "SELECT canonical_key, COUNT(*) n, COUNT(DISTINCT content_hash) h, "
        "GROUP_CONCAT(DISTINCT COALESCE(origin_source, aggregator, 'direct')) channels "
        "FROM entries WHERE canonical_key IS NOT NULL AND canonical_key<>'' "
        "GROUP BY canonical_key HAVING h>1 ORDER BY h DESC LIMIT 50"
    ).fetchall()
    return [{"canonical_key": r[0], "rows": r[1], "distinct_hashes": r[2], "channels": r[3]}
            for r in rows]


def table_stats(conn: sqlite3.Connection) -> dict:
    out = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                "AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        out[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    return out


def reap_stale_runs(conn: sqlite3.Connection, minutes: int = 30,
                    now: datetime | None = None) -> int:
    """把超过 N 分钟仍为 running 的执行记录标为 FAIL，避免中断留下假状态。"""
    now = now or datetime.now()
    rows = conn.execute("SELECT run_id, started_at FROM job_runs WHERE status='running'").fetchall()
    reaped = 0
    for run_id, started in rows:
        started_dt = parse_ts(started)
        if started_dt and (now - started_dt).total_seconds() < minutes * 60:
            continue
        conn.execute(
            "UPDATE job_runs SET status='FAIL', finished_at=?, "
            "detail_json=COALESCE(detail_json,'{}') || ? WHERE run_id=?",
            (now.isoformat(timespec="seconds"),
             json.dumps({"error": f"进程未正常结束（超过 {minutes} 分钟），已标记 FAIL"},
                        ensure_ascii=False), run_id),
        )
        reaped += 1
    conn.commit()
    return reaped
