#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""snippets.py — 代码片段提取（排障型情报权重）。

支持两类输入：
  - HTML：抽取 <pre><code>...</code></pre>（StackOverflow / 博客 / Issue 页面）
  - Markdown：抽取 ``` 围栏代码块（GitHub Issue / README）
用法：
  extract_html(raw) -> list[str]
  extract_md(text) -> list[str]
  render_block(snippets, max_chars=6000) -> str
"""
from __future__ import annotations

import html as html_lib
import re

_PRE_CODE = re.compile(r"<pre[^>]*>\s*<code[^>]*>([\s\S]*?)</code>\s*</pre>", re.I)
_PRE = re.compile(r"<pre[^>]*>([\s\S]*?)</pre>", re.I)
_MD_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n([\s\S]*?)```")
_TAG = re.compile(r"<[^>]+>")


def _clean(code: str) -> str:
    s = html_lib.unescape(code or "")
    s = _TAG.sub("", s)
    return s.strip("\n")


def extract_html(raw: str, limit: int = 20) -> list[str]:
    if not raw:
        return []
    found = [_clean(m) for m in _PRE_CODE.findall(raw)]
    if not found:
        found = [_clean(m) for m in _PRE.findall(raw)]
    out: list[str] = []
    for c in found:
        if len(c) >= 20 and c not in out:
            out.append(c)
        if len(out) >= limit:
            break
    return out


def extract_md(text: str, limit: int = 20) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for m in _MD_FENCE.findall(text):
        c = _clean(m)
        if len(c) >= 20 and c not in out:
            out.append(c)
        if len(out) >= limit:
            break
    return out


def render_block(snippets: list[str], max_chars: int = 6000) -> str:
    if not snippets:
        return ""
    parts = ["\n\n【代码片段】"]
    used = 0
    for i, s in enumerate(snippets, 1):
        chunk = f"\n```\n{s}\n```"
        if used + len(chunk) > max_chars:
            break
        parts.append(chunk)
        used += len(chunk)
    return "".join(parts) if len(parts) > 1 else ""
