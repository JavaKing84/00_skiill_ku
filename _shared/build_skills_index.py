"""build_skills_index.py — 扫描 skills/ 目录，生成机器可读索引 skills.json。

用法：python _shared/build_skills_index.py
输出：D:/00_skiill_ku/skills.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
OUT = ROOT / "skills.json"


def parse_frontmatter(text: str) -> dict:
    """极简 YAML frontmatter 解析（只处理本库用到的标量 / 行内列表）。"""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    meta: dict = {}
    for line in text[3:end].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key] = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key] = value.strip("'\"")
    return meta


def main() -> int:
    items = []
    for path in sorted(SKILLS_DIR.glob("*/*/SKILL.md")):
        meta = parse_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
        if not meta.get("name"):
            continue
        items.append({
            "name": meta.get("name"),
            "description": meta.get("description", ""),
            "version": meta.get("version", "0.0.0"),
            "triggers": meta.get("triggers", []),
            "not_triggers": meta.get("not_triggers", []),
            "path": path.parent.relative_to(ROOT).as_posix(),
            "entry": (path.parent / "SKILL.md").relative_to(ROOT).as_posix(),
        })

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "count": len(items),
        "skills": items,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[skills-index] 已生成 {OUT}，共 {len(items)} 个技能")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
