#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_registry.py — 能力注册表与适配文档结构校验。"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_STATUS = {"DISCOVERED", "CONFIGURED", "CONNECTED", "PASS", "PARTIAL",
                  "BLOCKED", "FAIL", "NOT_TESTED", "DEPRECATED"}
REQUIRED_FIELDS = ["id", "name", "description", "preferred_impl", "alternatives",
                   "depends_on", "install_steps", "config_requirements",
                   "verify_steps", "limits", "supported_clients", "status"]
REQUIRED_ADAPTERS = ["trae", "workbuddy", "loomi", "claude-code", "generic-agent"]


def main() -> int:
    failures = []
    reg = yaml.safe_load((ROOT / "CAPABILITY_REGISTRY.yaml").read_text(encoding="utf-8"))
    caps = reg.get("capabilities", [])
    if len(caps) < 10:
        failures.append(f"能力条目过少: {len(caps)}")
    ids = set()
    for c in caps:
        missing = [f for f in REQUIRED_FIELDS if f not in c]
        if missing:
            failures.append(f"{c.get('id')} 缺字段 {missing}")
        if c.get("status") not in ALLOWED_STATUS:
            failures.append(f"{c.get('id')} 状态非法 {c.get('status')}")
        if c.get("id") in ids:
            failures.append(f"ID 重复 {c.get('id')}")
        ids.add(c.get("id"))

    for a in REQUIRED_ADAPTERS:
        p = ROOT / "adapters" / a / "README.md"
        if not p.exists() or p.stat().st_size < 100:
            failures.append(f"适配文档缺失或过短: {a}")

    for doc in ["AGENTS.md", "INSTALLATION_GUIDE.md", "VERIFICATION_RULES.md", "CHANGELOG.md"]:
        if not (ROOT / doc).exists():
            failures.append(f"根文档缺失: {doc}")

    if failures:
        print("FAIL", failures)
        return 2
    print(f"PASS test_registry: {len(caps)} 项能力字段/状态枚举/5 适配文档/根文档 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
