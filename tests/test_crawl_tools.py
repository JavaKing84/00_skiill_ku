#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_crawl_tools.py — 爬虫 Skill 工具层验收（离线可复现）。

覆盖：页面分类、三引擎抽取兜底、平台矩阵数据结构、探测产物字段、
混剪渲染器参数、编码/BOM、凭据排除规则。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "01_crawler" / "scripts"))

import probe_site  # noqa: E402
import extract_article  # noqa: E402

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)
    print(("PASS " if cond else "FAIL ") + msg)


SSR_HTML = ("<html><head><title>Doc</title></head><body><article>"
            + "<p>" + ("real article content about scraping. " * 80) + "</p>"
            + "</article></body></html>")
SPA_HTML = ('<html><head><title>App</title></head><body><div id="app"></div>'
            '<script id="__NEXT_DATA__" type="application/json">{}</script></body></html>')
CAPTCHA_HTML = ("<html><head><title>安全验证</title></head><body>"
                "<p>请完成人机验证后继续访问</p></body></html>")


def main() -> int:
    # 1. 页面分类
    ssr = probe_site.classify_page(SSR_HTML)
    check(ssr["render_layer"] == "ssr" and ssr["visible_text_chars"] > 1500,
          f"分类：SSR 页判定正确（{ssr['render_layer']}, {ssr['visible_text_chars']} chars）")
    spa = probe_site.classify_page(SPA_HTML)
    check(spa["render_layer"] == "spa-shell" and spa["structured_data"],
          f"分类：SPA 空壳判定正确（{spa['render_layer']}）")
    cap = probe_site.classify_page(CAPTCHA_HTML)
    check(cap["blockers"]["captcha"] and cap["visible_text_chars"] < 200,
          f"分类：验证页识别正确（captcha={cap['blockers']['captcha']}）")
    # 误判回归：正文里出现 verify 不应判为验证码
    benign = probe_site.classify_page("<html><body><p>" + "we verify sources. " * 200 + "</p></body></html>")
    check(not benign["blockers"]["captcha"], "分类：正文含 verify 不误判为验证码")

    # 2. 抽取兜底
    text, engine = extract_article.extract(SSR_HTML, "builtin")
    check(engine == "builtin" and len(text) >= 200, f"抽取：builtin 兜底可用（{len(text)} chars）")
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "page.html"
        f.write_text(SSR_HTML, encoding="utf-8")
        out = Path(td) / "out.txt"
        p = subprocess.run([sys.executable, str(ROOT / "01_crawler" / "scripts" / "extract_article.py"),
                            "--file", str(f), "--engine", "builtin", "--out", str(out)],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        check(p.returncode == 0 and out.exists() and out.stat().st_size > 200,
              f"抽取：CLI 落盘成功（exit={p.returncode}, {out.stat().st_size if out.exists() else 0} B）")

    # 3. 平台矩阵结构
    m = ROOT / "01_crawler" / "reports" / "platform_matrix.json"
    check(m.exists(), "矩阵：platform_matrix.json 存在")
    if m.exists():
        d = json.loads(m.read_text(encoding="utf-8"))
        rows = d.get("rows", [])
        check(len(rows) >= 8 and d.get("public_reachable", 0) >= 5,
              f"矩阵：{len(rows)} 行、公开可达 {d.get('public_reachable')}")
        check(all("platform" in r and "kind" in r for r in rows), "矩阵：每行含 platform/kind")
        check("logged_in_probes" in d, "矩阵：含登录态探测结果")
        verdicts = {r["platform"] + "/" + r["kind"]: r.get("verdict") for r in rows}
        check(verdicts.get("douyin/logged_in") in ("BLOCKED_CHALLENGE", "LOGGED_OUT", "LOGGED_IN"),
              f"矩阵：登录态结论为实测值（{verdicts.get('douyin/logged_in')}）")

    # 4. 探测产物字段
    pj = ROOT / "_reports" / "probes" / "bili_popular_api.json"
    if pj.exists():
        d = json.loads(pj.read_text(encoding="utf-8"))
        check(d.get("ok") and d.get("json_ok") and d.get("api_code") == 0,
              f"探测：B 站公开 API 结构完整（code={d.get('api_code')}）")

    # 5. 混剪渲染器
    sys.path.insert(0, str(ROOT / "03_video" / "scripts"))
    import montage_edit  # noqa: E402
    check(set(montage_edit.GRADES) >= {"none", "dark_cool"}, "渲染：调色预设存在")
    edl = Path(r"E:\Trae_Video_Workspace\work\v4_edit\edl.json")
    if edl.exists():
        cfg = json.loads(edl.read_text(encoding="utf-8"))
        total = sum(float(s["dur"]) for s in cfg["segments"])
        check(55 <= total <= 65, f"渲染：EDL 总时长 {total:.2f}s 在 55–65s 区间")
        check(cfg["segments"][0]["start"] == 0 and "ref_02" in cfg["segments"][0]["src"],
              "渲染：开头保留原片（关键台词所在源）")
        check(len([s for s in cfg["segments"] if "broll" in s["src"]]) >= 2,
              "渲染：包含至少 2 个补充空镜")

    # 6. 编码与凭据规则
    bad = []
    for p in list((ROOT / "01_crawler" / "scripts").glob("*.py")) + \
             list((ROOT / "03_video" / "scripts").glob("*.py")):
        if p.read_bytes().startswith(b"\xef\xbb\xbf"):
            bad.append(p.name)
    check(not bad, f"编码：新增脚本无 BOM（{bad or 'none'}）")
    gi = ROOT / ".gitignore"
    check(gi.exists() and ".env" in gi.read_text(encoding="utf-8"), "安全：.gitignore 排除 .env")

    print()
    if failures:
        print(f"FAILED {len(failures)}:")
        for f in failures:
            print("  -", f)
        return 2
    print("PASS test_crawl_tools: 分类/抽取/矩阵/探测/渲染/编码/凭据规则 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
