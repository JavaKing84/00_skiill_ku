#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_triggers.py — 触发测试集的**静态规则检查**（不是模型路由测试）。

校验：
  - 正向用例：期望触发的规则文件必须覆盖该表达（tokens 命中）。
  - 负向用例：被排除的规则文件，其"负向触发"段必须写明该边界（tokens 命中）。
  - 组合用例：两条规则都必须覆盖各自部分。
并输出"静态检查 PASS / 真实路由 NOT_TESTED"的明确区分。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "trigger_cases.yaml"
failures: list[str] = []


def negative_section(text: str) -> str:
    """取规则文件中"负向"相关段落（负向触发 / 不触发）。"""
    idx = -1
    for key in ("负向触发", "不触发", "负向边界"):
        i = text.find(key)
        if i >= 0:
            idx = i if idx < 0 else min(idx, i)
    return text[idx:] if idx >= 0 else ""


def main() -> int:
    data = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    rules = data["rules"]
    texts = {}
    for key, path in rules.items():
        p = Path(path)
        if not p.exists():
            failures.append(f"规则文件缺失：{path}")
            continue
        texts[key] = p.read_text(encoding="utf-8")

    cases = data["cases"]
    pos = neg = combo = 0
    for c in cases:
        text = (c.get("text") or "")
        tokens = [str(t) for t in (c.get("tokens") or []) if t]
        expect = c.get("expect")
        if expect and expect != "none":
            body = texts.get(expect, "")
            hit = [t for t in tokens if t in body]
            if not hit:
                failures.append(f"{c['id']}：{expect} 规则未覆盖该表达（tokens={tokens}）")
            else:
                if c.get("combo"):
                    combo += 1
                else:
                    pos += 1
        if expect == "none":
            avoid = c.get("avoid")
            neg_text = negative_section(texts.get(avoid, ""))
            hit = [t for t in tokens if t in neg_text]
            if not hit:
                failures.append(f"{c['id']}：{avoid} 规则的负向段未写明该边界（tokens={tokens}）")
            else:
                neg += 1

    print(f"静态规则检查：正向覆盖 {pos} / 负向边界 {neg} / 组合 {combo}（共 {len(cases)} 用例）")
    print("真实模型路由测试：NOT_TESTED（需在新会话中由宿主 Agent 触发，本脚本不冒充路由证据）")
    if failures:
        print(f"FAILED {len(failures)}:")
        for f in failures:
            print("  -", f)
        return 2
    print("PASS test_triggers: 触发测试集静态规则检查全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
