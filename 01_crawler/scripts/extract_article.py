#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_article.py — 正文抽取（可降级三引擎）。

引擎优先级：trafilatura（可选依赖）→ readability-lxml（可选）→ 内置标签清洗（零依赖兜底）。
只对合法公开页面使用；不破解登录、不绕验证码。

用法：
  python extract_article.py --url https://example.com/post --out out.txt --json out.json
  python extract_article.py --file page.html --engine builtin
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))

from skillkit.http import HttpClient  # noqa: E402
from skillkit.policy import CrawlPolicy  # noqa: E402

MIN_CHARS = 200


def _builtin(raw: str) -> str:
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = html.unescape(body)
    return re.sub(r"\s+", " ", body).strip()


def extract(raw: str, engine: str = "auto") -> tuple[str, str]:
    """返回 (正文, 实际引擎)。"""
    engines = ([engine] if engine != "auto" else ["trafilatura", "readability", "builtin"])
    for eng in engines:
        text = ""
        if eng == "trafilatura":
            try:
                import trafilatura
                text = trafilatura.extract(raw, include_comments=False, include_tables=False) or ""
            except ImportError:
                continue
        elif eng == "readability":
            try:
                from readability import Document
                text = re.sub(r"<[^>]+>", " ", Document(raw).summary())
                text = html.unescape(re.sub(r"\s+", " ", text)).strip()
            except ImportError:
                continue
        else:
            text = _builtin(raw)
        if len(text) >= MIN_CHARS:
            return text, eng
    return _builtin(raw), "builtin"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--file", default="")
    ap.add_argument("--engine", default="auto", choices=["auto", "trafilatura", "readability", "builtin"])
    ap.add_argument("--out", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    if not args.url and not args.file:
        print("FAIL: 需要 --url 或 --file")
        return 2

    started = time.time()
    if args.url:
        client = HttpClient(CrawlPolicy(timeout_seconds=25, max_retries=2, min_interval_seconds=1.0))
        r = client.get(args.url)
        raw = r.text
        meta = {"url": args.url, "http_status": r.status_code,
                "content_type": (r.headers.get("Content-Type") or "").split(";")[0]}
    else:
        raw = Path(args.file).read_text(encoding="utf-8", errors="replace")
        meta = {"file": args.file}

    text, used = extract(raw, args.engine)
    result = {**meta, "engine": used, "chars": len(text),
              "elapsed_ms": int((time.time() - started) * 1000),
              "sufficient": len(text) >= MIN_CHARS, "text": text[:20000]}
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in result.items() if k != "text"}
        payload["preview"] = text[:300]
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"engine={used} chars={len(text)} sufficient={result['sufficient']} ms={result['elapsed_ms']}")
    print(text[:200].replace("\n", " "))
    return 0 if result["sufficient"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
