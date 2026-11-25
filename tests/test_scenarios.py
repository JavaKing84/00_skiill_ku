#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_scenarios.py — 多 Skill 协同场景 A/B/C 实跑。

A 爬虫 → TechRadar：本地合法 fixture 站点 → 采集 → 标准化 → 入库（临时库）→ 查询 → 重复采集验证去重 → 溯源
B TechRadar → 视频：从真实库检索选题 → 生成素材需求 → 素材验证/参考分析 → 渲染 → QC → 发布预览（dry-run）
C 规则协同：三条规则的协作段与触发用例互不冲突（静态）
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_shared"))
from skillkit.inteldb import IntelDB  # noqa: E402
from skillkit.manifest import CollectionManifest, CollectionRecord  # noqa: E402
from skillkit.policy import CrawlPolicy  # noqa: E402

REAL_DB = ROOT / "06_techradar" / "data" / "techradar.db"
failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)
    print(("PASS " if cond else "FAIL ") + msg)


FIXTURE = """<!doctype html><html><head><meta charset="utf-8"><title>Fixture Tech Radar</title></head>
<body><article><h1>Robotics VLA Release Notes</h1>
<p>New open-source vision-language-action model for robot manipulation, published 2026-11-17.</p>
<p>Includes dataset loader, evaluation script, and a 2B parameter checkpoint for edge inference.</p>
</article></body></html>"""


def serve_fixture(tmp: Path):
    from functools import partial
    web = tmp / "web"
    web.mkdir(parents=True, exist_ok=True)
    (web / "index.html").write_text(FIXTURE, encoding="utf-8")
    handler = partial(SimpleHTTPRequestHandler, directory=str(web))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/index.html"


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        httpd, url = serve_fixture(tdp)

        # ================= 场景 A：爬虫 → TechRadar =================
        policy = CrawlPolicy(min_interval_seconds=0.2)
        manifest = CollectionManifest(project="scenario-a")
        import requests
        s = requests.Session()
        s.trust_env = False
        r = s.get(url, headers={"User-Agent": policy.user_agent}, timeout=15)
        check(r.status_code == 200 and "Robotics VLA" in r.text, f"A1 本地 fixture 站点可访问（HTTP {r.status_code}）")

        title = "Robotics VLA Release Notes"
        rec = CollectionRecord(source_url=url, title=title, media_type="article",
                               source_name="local-fixture", http_status=r.status_code,
                               extra={"summary": r.text[:120], "fixture": True})
        manifest.add(rec)
        mpath = tdp / "assets_manifest.json"
        manifest.save(mpath)
        check(mpath.exists() and rec.license_status == "unknown",
              f"A2 采集结果写入 assets_manifest.json（license={rec.license_status}）")

        db = tdp / "techradar.db"
        shutil.copy2(REAL_DB, db)
        with IntelDB(db) as d:
            verdict = d.upsert_aggregated_entry(
                external_key="fixture:vla-release", aggregator="local-fixture",
                origin_source="local-fixture", url=url, title=title, author="fixture",
                published_at="2026-11-17T00:00:00Z", summary=r.text[:200], content=r.text[:500],
                category="ai", ai_category="ai", link_status="active",
                first_seen_at="2026-11-17T00:00:00Z", last_seen_at="2026-11-17T00:00:00Z",
                metrics={"points": 10}, extra={"fixture": True})
            check(verdict == "inserted", f"A3 标准化后入库（{verdict}）")
            verdict2 = d.upsert_aggregated_entry(
                external_key="fixture:vla-release", aggregator="local-fixture",
                origin_source="local-fixture", url=url, title=title, author="fixture",
                published_at="2026-11-17T00:00:00Z", summary=r.text[:200], content=r.text[:500],
                category="ai", ai_category="ai", link_status="active",
                first_seen_at="2026-11-17T00:00:00Z", last_seen_at="2026-11-18T00:00:00Z",
                metrics={"points": 10}, extra={"fixture": True})
            check(verdict2 == "updated", f"A4 重复采集为幂等更新（{verdict2}）")
            n = d.conn.execute("SELECT COUNT(*) FROM entries WHERE external_key='fixture:vla-release'").fetchone()[0]
            check(n == 1, f"A5 重复采集后仍只有 {n} 行（去重生效）")
            row = d.conn.execute(
                "SELECT origin_source, aggregator, url, canonical_key FROM entries WHERE external_key='fixture:vla-release'").fetchone()
            check(row["origin_source"] == "local-fixture" and row["aggregator"] == "local-fixture"
                  and row["url"] == url and row["canonical_key"],
                  f"A6 溯源完整：origin={row['origin_source']} agg={row['aggregator']} url 保持原样")

        q = subprocess.run([sys.executable, str(ROOT / "06_techradar" / "scripts" / "radar_query.py"),
                            "--db", str(db), "--text", "vision language action", "--limit", "5"],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        check(q.returncode == 0 and "hits=" in q.stdout and "hits=0" not in q.stdout,
              f"A7 入库后可通过查询检索：{q.stdout.strip().splitlines()[0] if q.stdout else ''}")
        httpd.shutdown()

        # ================= 场景 B：TechRadar → 视频 =================
        topic = subprocess.run([sys.executable, str(ROOT / "06_techradar" / "scripts" / "radar_query.py"),
                                "--db", str(REAL_DB), "--scenario", "ai-robot", "--limit", "5"],
                               capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        check(topic.returncode == 0 and "hits=" in topic.stdout,
              f"B1 从真实情报库检索选题：{topic.stdout.strip().splitlines()[0] if topic.stdout else ''}")
        sel = json.loads((ROOT / "_reports" / "q_robot_after.json").read_text(encoding="utf-8")) \
            if (ROOT / "_reports" / "q_robot_after.json").exists() else {"hits": []}
        needs = []
        for h in sel.get("hits", [])[:2]:
            needs.append({"topic": h["title"], "url": h["url"], "category": h.get("category")})
        check(len(needs) >= 1, f"B2 由情报生成素材需求 {len(needs)} 条")

        clip = tdp / "clip.mp4"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=4",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-af", "volume=-9dB",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)],
                       capture_output=True, text=True, timeout=300)
        ana = tdp / "analysis"
        pa = subprocess.run([sys.executable, str(ROOT / "03_video" / "scripts" / "reference_analyze.py"),
                             "--video", str(clip), "--out", str(ana)],
                            capture_output=True, text=True, cwd=str(ROOT), timeout=600)
        check(pa.returncode == 0 and (ana / "reference_style.json").exists(),
              f"B3 参考分析产出 {pa.stdout.strip().splitlines()[0] if pa.stdout else ''}")

        out = tdp / "final.mp4"
        pr = subprocess.run([sys.executable, str(ROOT / "03_video" / "scripts" / "render.py"),
                             "--inputs", str(clip), "--out", str(out), "--aspect", "9:16",
                             "--subtitle", (needs[0]["topic"][:20] if needs else "科技情报"), "--qc"],
                            capture_output=True, text=True, cwd=str(ROOT), timeout=900)
        check(pr.returncode == 0 and out.exists() and "QC PASS" in pr.stdout,
              f"B4 渲染出片并自动 QC：exit={pr.returncode}")

        prev = tdp / "publish_preview.md"
        pp = subprocess.run([sys.executable, str(ROOT / "03_video" / "scripts" / "publish_preview.py"),
                             "--video", str(out), "--platform", "douyin", "--account", "13800001234",
                             "--title", (needs[0]["topic"][:24] if needs else "t"),
                             "--tags", "机器人,AI", "--out", str(prev)],
                            capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        ptxt = prev.read_text(encoding="utf-8") if prev.exists() else ""
        check(pp.returncode == 0 and "DRY-RUN" in ptxt and "13800001234" not in ptxt,
              "B5 生成发布预览（dry-run，账号脱敏，未真实发布）")

        # ================= 场景 C：规则协同 =================
        import re
        rule_dir = Path.home() / ".trae-cn" / "user_rules"
        by_desc: dict[str, str] = {}
        for p in sorted(rule_dir.glob("rule-*.md")):
            text = p.read_text(encoding="utf-8")
            m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
            desc = ""
            if m:
                for line in m.group(1).splitlines():
                    if line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip()
            by_desc[desc or p.stem] = text
        video_r = [by_desc["视频剪辑与制作路由"]] if "视频剪辑与制作路由" in by_desc else []
        crawl_r = [by_desc["爬虫与网站数据采集路由"]] if "爬虫与网站数据采集路由" in by_desc else []
        radar_r = [by_desc["TechRadar技术情报与研究路由"]] if "TechRadar技术情报与研究路由" in by_desc else []
        check(len(video_r) == 1 and len(crawl_r) == 1 and len(radar_r) == 1,
              f"C1 三条独立规则各一份（video={len(video_r)} crawl={len(crawl_r)} techradar={len(radar_r)}，"
              f"规则文件总数 {len(by_desc)}）")
        check(all("多 Skill 协作" in t for t in (video_r + crawl_r + radar_r)),
              "C2 三条规则都定义了多 Skill 协作段")
        check("TechRadar技术情报与研究路由" in video_r[0] and "视频剪辑与制作路由" in crawl_r[0]
              and "TechRadar技术情报与研究路由" in crawl_r[0] and "视频剪辑与制作路由" in radar_r[0],
              "C3 跨规则互指正确（研究→视频、抓取→情报）")
        old = by_desc.get("会议纪要与长文档路由", "")
        check("会议" in old and "轻量" in old, "C4 旧规则保留会议纪要与轻量报错约定")

    print()
    if failures:
        print(f"FAILED {len(failures)}:")
        for f in failures:
            print("  -", f)
        return 2
    print("PASS test_scenarios: 场景A(爬虫→情报)/B(情报→视频)/C(规则协同) 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
