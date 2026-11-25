"""统一采集清单契约（素材采集与技术情报共用）。

两类适配器写入同一种记录结构，复用下载、哈希、去重、存储、日志能力：
  - material 适配器：网页/文章/图片/视频/音频/字幕/开源项目素材
  - intel    适配器：技术情报条目（帖子/讨论/release/论文）

记录字段为统一契约 v1；未知许可一律 `unknown`，禁止默认可商用。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .hashing import sha256_file

SCHEMA_VERSION = "collection-manifest-v1"
MEDIA_TYPES = {"webpage", "article", "image", "video", "audio", "subtitle", "repo", "post"}


@dataclass
class CollectionRecord:
    source_url: str
    title: str
    media_type: str  # 见 MEDIA_TYPES
    collected_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    published_at: str | None = None
    source_name: str | None = None
    file_path: str | None = None
    sha256: str | None = None
    license_status: str = "unknown"  # unknown | licensed | public-domain | cc-* | forbidden
    http_status: int | None = None
    adapter: str = "material"  # material | intel
    status: str = "discovered"  # discovered | downloaded | verified | failed | skipped
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.media_type not in MEDIA_TYPES:
            raise ValueError(f"media_type 必须属于 {sorted(MEDIA_TYPES)}，收到 {self.media_type!r}")
        if self.adapter not in {"material", "intel"}:
            raise ValueError("adapter 只能是 material 或 intel")

    def attach_file(self, path: str | Path) -> None:
        """下载落盘后调用：登记路径并计算哈希。"""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        self.file_path = str(p)
        self.sha256 = sha256_file(p)
        self.status = "downloaded"


class CollectionManifest:
    """内存清单 + JSON 落盘；按 (URL 或 sha256) 去重。"""

    def __init__(self, project: str):
        self.project = project
        self.schema_version = SCHEMA_VERSION
        self.records: list[CollectionRecord] = []
        self._seen_urls: set[str] = set()
        self._seen_hashes: set[str] = set()

    def add(self, record: CollectionRecord) -> str:
        """返回 inserted | dup_url | dup_hash。"""
        if record.source_url in self._seen_urls:
            return "dup_url"
        if record.sha256 and record.sha256 in self._seen_hashes:
            return "dup_hash"
        self.records.append(record)
        self._seen_urls.add(record.source_url)
        if record.sha256:
            self._seen_hashes.add(record.sha256)
        return "inserted"

    def verify_files(self) -> int:
        """对已下载记录重新哈希校验，返回不一致条数；同时把状态置 verified/failed。"""
        bad = 0
        for r in self.records:
            if not r.file_path:
                continue
            p = Path(r.file_path)
            if not p.exists():
                r.status = "failed"
                bad += 1
                continue
            actual = sha256_file(p)
            if r.sha256 and actual != r.sha256:
                r.status = "failed"
                bad += 1
            else:
                r.sha256 = actual
                r.status = "verified"
        return bad

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(self.records),
            "records": [asdict(r) for r in self.records],
        }

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: str | Path) -> "CollectionManifest":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        m = cls(project=data["project"])
        for raw in data["records"]:
            m.add(CollectionRecord(**raw))
        return m
