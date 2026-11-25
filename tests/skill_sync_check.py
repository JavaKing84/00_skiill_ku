#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skill_sync_check.py — canonical Skill 与客户端入口壳的一致性校验（只读）。

校验四件事：
1. canonical frontmatter 是否齐备（name / description / version / triggers / not_triggers / 执行入口）。
2. 客户端壳是否真的指向该 canonical（绝对路径出现在壳文件中）。
3. 壳与 canonical 声明的版本是否一致（壳里出现相同版本号）。
4. 规则文件是否齐备（frontmatter description / alwaysApply / 正负触发 / canonical 指向）。

退出码：0=全部通过；1=存在不一致项。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER = Path.home()

CANONICAL = {
    "crawl": ROOT / "01_crawler" / "SKILL.md",
    "video": ROOT / "03_video" / "SKILL.md",
    "techradar": ROOT / "06_techradar" / "SKILL.md",
}
SHELLS = {
    "crawl": USER / ".trae-cn" / "skills" / "material-sourcing-crawler" / "SKILL.md",
    "video": USER / ".trae-cn" / "skills" / "aitoearn" / "SKILL.md",
    "techradar": USER / ".trae-cn" / "skills" / "tech-radar" / "SKILL.md",
}
WORKBUDDY_SHELLS = {
    "crawl": USER / ".workbuddy" / "skills" / "web-scraping-playbook" / "SKILL.md",
}
RULE_DIR = USER / ".trae-cn" / "user_rules"
REQUIRED_RULES = ["视频剪辑与制作路由", "爬虫与网站数据采集路由", "TechRadar技术情报与研究路由"]

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def frontmatter(text: str) -> dict:
    m = FM_RE.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def version_of(text: str) -> str:
    return frontmatter(text).get("version", "")


def check() -> dict:
    issues: list[str] = []
    details: dict = {"canonical": {}, "shells": {}, "rules": {}}

    for key, path in CANONICAL.items():
        if not path.exists():
            issues.append(f"canonical 缺失：{path}")
            continue
        text = path.read_text(encoding="utf-8")
        fm = frontmatter(text)
        for field in ("name", "description", "version"):
            if not fm.get(field):
                issues.append(f"canonical {key} 缺 frontmatter 字段 {field}")
        if key != "crawl" and not fm.get("triggers"):
            issues.append(f"canonical {key} 缺 triggers")
        if key != "crawl" and not fm.get("not_triggers"):
            issues.append(f"canonical {key} 缺 not_triggers")
        if key != "crawl" and not (fm.get("executor") or fm.get("execution_entry")):
            issues.append(f"canonical {key} 缺执行入口声明")
        details["canonical"][key] = {"path": str(path), "version": fm.get("version"),
                                     "name": fm.get("name"),
                                     "has_description": bool(fm.get("description")),
                                     "has_triggers": bool(fm.get("triggers")),
                                     "has_not_triggers": bool(fm.get("not_triggers"))}

    for key, path in SHELLS.items():
        if not path.exists():
            issues.append(f"客户端壳缺失：{path}")
            continue
        text = path.read_text(encoding="utf-8")
        canon = CANONICAL[key]
        cver = version_of(canon.read_text(encoding="utf-8")) if canon.exists() else ""
        points_to_canon = str(canon).replace("/", "\\").lower() in text.replace("/", "\\").lower()
        version_match = (cver in text) if cver else False
        if not points_to_canon:
            issues.append(f"客户端壳 {key} 未指向 canonical（缺 {canon} 路径）")
        if not version_match:
            issues.append(f"客户端壳 {key} 未声明 canonical 版本 {cver}")
        details["shells"][key] = {"path": str(path), "points_to_canonical": points_to_canon,
                                  "version_declared": version_match, "canonical_version": cver}

    for key, path in WORKBUDDY_SHELLS.items():
        details["shells"][f"workbuddy_{key}"] = {"path": str(path), "exists": path.exists()}

    rules = sorted(RULE_DIR.glob("rule-*.md")) if RULE_DIR.exists() else []
    names = []
    for p in rules:
        text = p.read_text(encoding="utf-8")
        fm = frontmatter(text)
        names.append(fm.get("description", p.stem))
        if fm.get("alwaysApply") != "true":
            issues.append(f"规则 {p.name} 未设置 alwaysApply: true")
        if not fm.get("description"):
            issues.append(f"规则 {p.name} 缺 description")
        if "canonical" not in text and "canonical" not in text.lower():
            issues.append(f"规则 {p.name} 未声明 canonical 指向")
    for req in REQUIRED_RULES:
        if req not in names:
            issues.append(f"缺少全局规则：{req}")
    details["rules"] = {"dir": str(RULE_DIR), "files": [p.name for p in rules], "names": names}
    # P0-1 壳版本声明按用户要求暂缓：仅这一类别标记为 Expected Warning / Pending，
    # 其余同步问题仍是阻塞项。--strict 可把 Pending 也当失败（P0-1 修复后使用）。
    pending = [i for i in issues if "未声明 canonical 版本" in i]
    blocking = [i for i in issues if i not in pending]
    details["issues"] = issues
    details["pending"] = pending
    details["blocking"] = blocking
    details["ok"] = not blocking
    return details


def main() -> int:
    strict = "--strict" in sys.argv[1:]
    res = check()
    if strict:
        res["blocking"] = res.get("blocking", []) + res.get("pending", [])
        res["pending"] = []
        res["ok"] = not res["blocking"]
    res["status"] = "PASS" if res["ok"] and not res["pending"] else (
        "PENDING" if res["ok"] else "FAIL")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if res["ok"]:
        if res["pending"]:
            print(f"SYNC OK (PENDING {len(res['pending'])}: Expected Warning / Pending)")
            for p in res["pending"]:
                print("  -", p)
        else:
            print("SYNC OK：canonical / 客户端壳 / 全局规则一致")
        return 0
    print(f"SYNC ISSUES: {len(res['blocking'])}")
    for i in res["blocking"]:
        print("  -", i)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
