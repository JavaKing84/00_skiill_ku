#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_inventory.py — 生成技能库 inventory.json（Phase 0 审计用）。

规则：
- 遍历根目录全部文件；.git 内部对象不逐个哈希，只记录 git commit。
- 文本/代码类文件记录 SHA256；二进制大文件只记录大小。
- 输出 JSON：目录、文件、git 仓库、入口文件清单、统计。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skillkit.hashing import sha256_file  # noqa: E402

TEXT_SUFFIXES = {".md", ".py", ".mjs", ".js", ".json", ".yaml", ".yml", ".csv", ".txt", ".ps1", ".html", ".css"}
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__"}


def git_commit(repo: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=20,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"D:\00_skiill_ku")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    root = Path(args.root)

    files, repos, entries = [], [], []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            if path.is_dir() and path.name == ".git":
                commit = git_commit(path.parent)
                repos.append({"repo": str(path.parent.relative_to(root)), "head_commit": commit})
            continue
        if path.is_dir():
            continue
        stat = path.stat()
        total_bytes += stat.st_size
        suffix = path.suffix.lower()
        rec = {
            "path": str(path.relative_to(root)),
            "bytes": stat.st_size,
            "suffix": suffix,
            "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        }
        if suffix in TEXT_SUFFIXES and stat.st_size <= 2_000_000:
            rec["sha256"] = sha256_file(path)
        files.append(rec)
        if path.name in ("SKILL.md", "AGENTS.md", "README.md") or path.name.endswith("_index.md"):
            entries.append(rec["path"])

    suffix_count: dict[str, int] = {}
    for f in files:
        suffix_count[f["suffix"] or "<none>"] = suffix_count.get(f["suffix"] or "<none>", 0) + 1

    inventory = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "suffix_count": dict(sorted(suffix_count.items(), key=lambda kv: -kv[1])),
        "git_repos": repos,
        "entry_files": sorted(set(entries)),
        "files": files,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(inventory, f, ensure_ascii=False, indent=2)
    print(f"OK files={len(files)} repos={len(repos)} bytes={total_bytes} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
