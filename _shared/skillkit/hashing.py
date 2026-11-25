"""文件哈希与内容去重。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable


def sha256_file(path: str | Path, chunk_size: int = 1 << 20) -> str:
    """计算文件 SHA256，分块读取，适合大视频。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dedupe_by_hash(paths: Iterable[str | Path]) -> dict[str, list[str]]:
    """按哈希分组，返回 {hash: [path,...]}，长度>1 的组即重复文件。"""
    groups: dict[str, list[str]] = {}
    for p in paths:
        digest = sha256_file(p)
        groups.setdefault(digest, []).append(str(p))
    return {k: v for k, v in groups.items() if len(v) > 1}
