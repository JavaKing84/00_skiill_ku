#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ingest_case_notes.py — 把实战案例写成 knowledge_base 条目（可重复执行，按 URL+标题去重）。

为什么单独一个脚本：
  radar_query.py 是只读检索工具，不具备写入能力；案例沉淀走本项目的标准入库管道
  （run_source → ingest → IntelDB.add_entry），才能同时维护 FTS 索引、标签表与 source_registry。

用法：
  python ingest_case_notes.py              # 写入默认库
  python ingest_case_notes.py --db <path>  # 写入指定库（建议先写副本验证）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared"))

from skillkit.inteldb import IntelDB  # noqa: E402
from skillkit.pipeline import Record, SourceSpec, run_source  # noqa: E402
from skillkit.sources import ensure_registry  # noqa: E402

PUBLISHED = "2026-11-24T10:40:00Z"
SOURCE_ID = "knowledge_base"          # 与 radar_query.TECH_SOURCE_PRIORITY 的首位对齐

NOTES: list[dict] = [
    {
        "url": "https://www.reddit.com/r/LocalLLaMA/new.json",
        "title": "【实战】Reddit 403 判别：先 200 后 403 属速率封禁，DOM 降级与离屏浏览器参数",
        "category": "anti-bot",
        "tags": ["case-study", "anti-bot", "browser-automation", "reddit", "403"],
        "summary": (
            "同一出口先成功采到 40 条，4 分钟后 .json/HTML/old./api./oauth. 全部返回 403 拦截页。"
            "结论：这是速率/行为封禁而非 ASN 永久封禁。判别规则：同 IP 短时间内先 200 后 403 → 冷却 ≥6h、"
            "单线程单页、间隔 25–45s、指数退避；持续 403 才考虑换出口。"
            "接口降级链：JSON 403 → 真实浏览器 HTML → DOM 提取（Reddit 用 shreddit-post 的 "
            "post-title/permalink/created-timestamp/author/score/comment-count）→ 官方通道 → 标记 BLOCKED。"
            "curl_cffi 只改 TLS/HTTP2 指纹，改不了 IP 信誉与请求频率。"
        ),
        "content": (
            "[时间线·本地时间 2026-11-24]\n"
            "18:32:58 4 个 sub × 2 页连续请求，40 条入库成功\n"
            "18:32:59 源状态写入「站点按出口 IP 返回 403」\n"
            "18:36:14 之后 .json / /new/ / old.reddit / api.reddit / oauth.reddit 全部 403（190240B 拦截页）\n"
            "同期 api/v1/access_token 返回 401（该端点未封），可证拦截发生在数据域而非认证域\n\n"
            "[403 判别树]\n"
            "同一出口同一 UA 最近成功过？\n"
            " ├─ 是（先 200 后 403）→ 速率/行为封禁：停止请求，冷却 ≥6h；恢复时单线程单页、"
            "请求间隔 25–45s、失败按 2/4/8 分钟指数退避\n"
            " └─ 否（一直 403）→ 才可能是 IP/ASN 封禁，此时换出口才有意义\n"
            "实测：换节点等于换一个 IP 再打一遍同样的 8 连发，4 分钟后得到同样的 403，"
            "只会把限流升级成 IP 级封禁。\n\n"
            "[接口降级链]\n"
            "① JSON 接口 200 → 直接解析；403/429 → ②，不要立刻重试同一接口\n"
            "② 真实浏览器加载 HTML 列表页：200 且有服务端渲染节点 → 提 DOM；SPA 空壳 → 等渲染；403 → ③\n"
            "③ 官方替代通道（RSS/OAuth/聚合）→ 都不可用则标记 BLOCKED，不伪造数据\n\n"
            "[浏览器参数]\n"
            "--headless=new 暴露 HeadlessChrome UA 片段、缺失 GPU/音频栈等特征，"
            "高级风控（Cloudflare/Reddit/DataDome）可稳定识别；\n"
            "离屏真实窗口 --window-position=-32000,-32000 --window-size=1440,900 保留完整渲染栈，"
            "检测面与普通窗口一致，代价是必须有交互桌面（SYSTEM 服务会话下不可用）。\n"
            "本案例 403 属 IP 层，两种模式结果相同，无法据此比较检测率——别把经验当已证结论。\n\n"
            "[指纹能力边界]\n"
            "curl_cffi(impersonate=\"chrome\") 可伪装 TLS/JA3、HTTP2 帧序、header 顺序；"
            "改不了 ASN/IP 信誉与高频行为模式。换指纹后状态码不变 → 拦截不在指纹层。\n\n"
            "[关联]\n"
            "详细证据见 D:\\00_skiill_ku\\06_techradar\\_reports\\lifecycle\\ultimate_fix.md 第 8 节"
        ),
    },
    {
        "url": "https://ppc.land/reddit-to-halt-public-data-api-access-in-march-2027-as-14-000-apps-register/",
        "title": "【架构决策】Reddit RSS 停服后的替代路径：Folo 聚合中转，而非加强反爬对抗",
        "category": "engineering-decision",
        "tags": ["case-study", "engineering-decision", "api-change", "reddit", "folo"],
        "summary": (
            "Reddit 于 2026-09-30 公告：RSS 2026-11-13 停服；新 API 访问申请 2026-10-31 停止受理；"
            "公共 Data API 2027-03 关闭，官方明确针对爬虫并已提起诉讼。"
            "结论：合法自动化入口正在关闭，加强对抗是错方向。决策：改用第三方聚合服务 Folo 中转——"
            "由 Folo 服务端取数，本地只调 api.folo.is，不触碰目标站 IP 风控，采集代码零改动。"
        ),
        "content": (
            "[政策时间点]\n"
            "2026-09-30 Reddit 公告：RSS 于 2026-11-13 停止服务；剩余公共 Data API 2027-03 关闭；"
            "新 API 访问申请已于 2026-10-31 停止受理；官方表述针对 scraping 与 AI 抓取，并对多家公司提起诉讼。\n\n"
            "[决策]\n"
            "放弃：换节点/换指纹/带登录 Cookie 的直采路线。\n"
            "采用：Folo 聚合中转。理由：\n"
            "1) 抓取行为发生在 Folo 服务端，本地不产生对 Reddit 的请求，不受本机出口 IP 影响；\n"
            "2) 复用已有通道：collect_folo.py 走 api.folo.is，本机实测 SUCCESS（单轮 54 条）；\n"
            "3) 不需要代理软件 secret、不需要登录 Cookie、不增加封号面。\n\n"
            "[代价与边界]\n"
            "取决于用户在 Folo 客户端是否订阅了对应 subreddit 源，覆盖范围由订阅决定而非代码；\n"
            "Folo 侧的内容许可与留存策略需自行确认，入库时保留 origin_source 溯源，不冒充独立来源。\n\n"
            "[备选]\n"
            "Reddit Devvit 开发者平台 / 商业数据协议；或采购住宅出口 + 存量已获批凭据（新申请已关闭）。\n\n"
            "[教训]\n"
            "动手前先确认目标平台当前是否还有合法自动化入口；政策关闭时改架构，不是加强对抗。"
        ),
    },
    {
        "url": "https://playwright.dev/python/docs/api/class-browsertype",
        "title": "【工程规范】本地代理探测（204 校验）、Playwright 代理注入与浏览器进程精准管理",
        "category": "engineering-decision",
        "tags": ["case-study", "engineering-decision", "browser-automation", "proxy", "windows"],
        "summary": (
            "代理客户端（Karing/Clash 系）通常不写系统代理，浏览器与脚本会静默直连。"
            "规范做法：探测本机代理端口并用 gstatic/generate_204 校验（HTTP 204 才算通），"
            "命中即用，不读任何节点凭据；Playwright 启动 Chrome 时注入 --proxy-server。"
            "调试端口必须专用（9333），否则会静默接管用户其它 Chrome 会话；"
            "清理进程只按专用 user-data-dir 或 PID 精确匹配，禁止 taskkill /F /IM chrome.exe。"
        ),
        "content": (
            "[代理探测]\n"
            "候选优先级：TECH_RADAR_PROXY（显式）→ Karing 3067/3066/3065 → Clash 7897/7890/7891 → "
            "v2rayN 10809/10808/1080。\n"
            "校验目标 https://www.gstatic.com/generate_204，只有 HTTP 204 才判定链路可用；"
            "拿到 4xx/5xx 说明链路已通但目标站策略拒绝，与代理可用性无关。\n"
            "边界：只探测端口，不提取代理软件的 secret/订阅/节点凭据（爬虫库 SKILL C10）。\n\n"
            "[Playwright 注入]\n"
            "chrome.exe --proxy-server=http://127.0.0.1:<port> ... ；"
            "Chrome 默认跟随系统代理，而 Karing 默认不写系统代理，因此必须显式注入，否则脚本静默直连。\n"
            "实测：注入前 proxy_in_use=False 且页面行为与配置预期不符；注入后命令行可见 --proxy-server，"
            "代理生效可验证。\n\n"
            "[进程与端口]\n"
            "CDP 端口固定用 9333（TECH_RADAR_CDP_PORT 可覆盖）。原因：9222 会被用户其它调试会话占用，"
            "_cdp_ok() 只看 /json/version 是否 200，会静默接管别人的浏览器（实测接管到 BOSS直聘 会话），"
            "导致「登录态可用/403」的判定全部失真。\n"
            "清理：只杀 _profile_pids() 匹配到的 * --user-data-dir=*_browser_profile* 进程，"
            "逐 PID taskkill；禁止全局 /IM（爬虫库 SKILL C11）。\n\n"
            "[计划任务]\n"
            "不要用 SYSTEM +「无论是否登录都运行」：浏览器登录态在用户配置目录、代理客户端在用户会话，"
            "SYSTEM 上下文两者都拿不到，且无交互桌面时离屏窗口也起不来。\n\n"
            "[落地文件]\n"
            "06_techradar/scripts/proxy_env.py（探测）、websession.py（注入 + 9333 + PID 清理）、"
            "collect_reddit.py（HttpClient 注入 proxy）"
        ),
    },
]


def build_records() -> list[Record]:
    return [Record(
        url=n["url"], title=n["title"], published_at=PUBLISHED,
        summary=n["summary"], content=n["content"],
        author="techradar-local", category=n["category"], tags=n["tags"],
        external_key=f"case:{n['url']}",
        extra={"note_type": "case_study", "captured_at": PUBLISHED,
               "origin_report": r"D:\00_skiill_ku\06_techradar\_reports\lifecycle\ultimate_fix.md"},
    ) for n in NOTES]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "06_techradar" / "data" / "techradar.db"))
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"FAIL: 情报库不存在 {db_path}")
        return 2

    with IntelDB(db_path) as db:
        ensure_registry(db.conn)
        spec = SourceSpec(
            source_id=SOURCE_ID,
            source_name="知识库（实战案例与工程决策）",
            source_type="note",
            channel="internal",
            fetch=build_records,
            auth_required=False,
        )
        result = run_source(db, db.conn, spec)
        print(f"{SOURCE_ID} status={result['status']} fetched={result['fetched']} "
              f"inserted={result['inserted']} dedup={result['deduped']} "
              f"quarantined={result['quarantined']} error={result['error']}")
    return 0 if result["inserted"] + result["deduped"] == len(NOTES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
