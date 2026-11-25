#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_skillkit_contract.py — 共享契约：清单枚举、两级去重、断点、脱敏。"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_shared"))

from skillkit.manifest import CollectionManifest, CollectionRecord  # noqa: E402
from skillkit.hashing import sha256_bytes  # noqa: E402
from skillkit.policy import CrawlPolicy, Checkpoint  # noqa: E402
from skillkit.loggingx import mask  # noqa: E402


def main() -> int:
    failures = []

    # 1. 枚举校验
    try:
        CollectionRecord(source_url="u", title="t", media_type="not-a-type")
        failures.append("media_type 枚举未拦截非法值")
    except ValueError:
        pass

    # 2. URL 级去重
    m = CollectionManifest(project="t")
    r1 = CollectionRecord(source_url="https://x/a", title="a", media_type="post", adapter="intel")
    r2 = CollectionRecord(source_url="https://x/a", title="a", media_type="post", adapter="intel")
    if m.add(r1) != "inserted" or m.add(r2) != "dup_url":
        failures.append("URL 去重失败")

    # 3. 内容哈希级去重（同 URL 不同，用 attach_file 造同哈希）
    with tempfile.TemporaryDirectory() as td:
        f1, f2 = Path(td) / "a.bin", Path(td) / "b.bin"
        f1.write_bytes(b"same-bytes"); f2.write_bytes(b"same-bytes")
        if sha256_bytes(f1.read_bytes()) != sha256_bytes(f2.read_bytes()):
            failures.append("哈希不一致")
        m2 = CollectionManifest(project="t2")
        ra = CollectionRecord(source_url="https://x/1", title="1", media_type="image")
        rb = CollectionRecord(source_url="https://x/2", title="2", media_type="image")
        ra.attach_file(f1); rb.attach_file(f2)
        if m2.add(ra) != "inserted" or m2.add(rb) != "dup_hash":
            failures.append("内容哈希去重失败")

        # 4. 清单落盘/重载/校验
        p = m2.save(Path(td) / "assets_manifest.json")
        loaded = CollectionManifest.load(p)
        if loaded.verify_files() != 0 or loaded.records[0].status != "verified":
            failures.append("清单重载或文件校验失败")

        # 5. 断点
        cp = Checkpoint(Path(td) / "cp.json")
        cp.mark("u1"); cp2 = Checkpoint(Path(td) / "cp.json")
        if not cp2.has("u1"):
            failures.append("断点持久化失败")

    # 6. 退避单调性 & 脱敏
    pol = CrawlPolicy()
    if not (pol.backoff(1) < pol.backoff(2)):
        failures.append("退避未递增")
    masked = mask('headers X-Api-Key: cn_abcdef1234567890ABCDEF and password="hello123456"')
    if "cn_abcdef" in masked or "hello123456" in masked or "MASKED" not in masked:
        failures.append(f"脱敏失败: {masked}")

    if failures:
        print("FAIL", failures)
        return 2
    print("PASS test_skillkit_contract: 枚举/URL去重/哈希去重/清单持久化/断点/退避/脱敏 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
