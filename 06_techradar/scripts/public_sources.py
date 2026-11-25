#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""public_sources.py — 通道 A：零凭证公开数据源适配器。

全部来源均无需账号 / Cookie / API Key：
  hn_frontpage      Hacker News（Algolia 公开搜索）
  github_search     GitHub 公开仓库搜索 API
  github_releases   GitHub 公开 releases Atom
  hf_models         Hugging Face 公开模型（trending）
  hf_datasets       Hugging Face 公开数据集（trending）
  hf_daily_papers   Hugging Face Daily Papers（真实 arXiv 论文）
  arxiv             arXiv 公开 API（cs.AI/cs.LG/cs.RO/cs.CL）
  rss_official      官方技术博客公开 RSS/Atom
  github_issues     GitHub Issues 排障检索（按报错特征搜 issue，含代码块）
  stackoverflow     Stack Overflow 排障问答（公开 API，含代码块）
  radar_zcl         资源雷达公开只读 API（二级聚合）
  sec_rss           全球头部黑客/安全媒体 RSS（12 站，逐站故障隔离）
  github_advisories GitHub Security Advisories 公开 API（GHSA/CVE）
  cisa_kev          CISA 已知被利用漏洞目录（KEV，公开 JSON）
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
from skillkit.http import FetchError, HttpClient  # noqa: E402
from skillkit.pipeline import Record, SourceSpec, iso  # noqa: E402

ATOM_NS = "{http://www.w3.org/2005/Atom}"
TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    return html.unescape(TAG_RE.sub(" ", raw)).strip()


# ---------------------------------------------------------------- 代码块 / 语境标签
CODE_BLOCK_RE = re.compile(
    r"<pre[^>]*>\s*<code[^>]*>(.*?)</code>\s*</pre>|<pre[^>]*>(.*?)</pre>",
    re.S | re.I)


def _extract_code_blocks(raw: str | None, limit: int = 5, max_chars: int = 4000) -> list[str]:
    """从正文 HTML 中抽取 <pre><code> 代码块，去标签后原文保留缩进。

    技术博客与 Issue 的排障价值大半在代码块里（报错栈、复现脚本、修复 diff），
    只存纯文本摘要会把它们压成一行噪音，因此单独抽出并存入 extra_json.code_blocks。
    """
    if not raw:
        return []
    blocks: list[str] = []
    for m in CODE_BLOCK_RE.finditer(raw):
        body = m.group(1) or m.group(2) or ""
        code = html.unescape(TAG_RE.sub("", body)).replace("\r\n", "\n").strip()
        if len(code) < 20:            # 太短的多是行内片段，不是可复用代码
            continue
        blocks.append(code[:max_chars])
        if len(blocks) >= limit:
            break
    return blocks


# 技术语境标签：命中关键词即打标，用于雷达按「问题类型」检索而不是按来源检索
CONTEXT_TAG_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("anti-bot", ("403", "429", "cloudflare", "captcha", "waf", "rate limit", "rate-limit",
                  "bot detection", "anti-bot", "anti-scraping", "反爬", "封禁", "风控")),
    ("browser-automation", ("playwright", "selenium", "puppeteer", "headless", "cdp",
                            "browser automation", "chromium", "framework 错误")),
    ("api-change", ("deprecated", "deprecation", "breaking change", "sunset", "end of life",
                    "eol", "api shutdown", "no longer", "stopped accepting", "停服", "下线", "关闭")),
    ("engineering-decision", ("trade-off", "tradeoff", "architecture", "migration",
                              "替代方案", "取舍", "架构", "选型", "决策")),
]


def _context_tags(*texts: str | None, limit: int = 3) -> list[str]:
    blob = " ".join(t for t in texts if t).lower()
    hits = [tag for tag, keys in CONTEXT_TAG_RULES if any(k in blob for k in keys)]
    return hits[:limit]


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        return iso(parsedate_to_datetime(value))
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return iso(datetime.strptime(value, fmt))
        except ValueError:
            continue
    return None


BARE_AMP_RE = re.compile(r"&(?!(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]{1,8});)")


def _load_xml(xml_text: str) -> ET.Element:
    """解析 XML；遇到裸 & 等脏字符时做一次清洗重试（安全媒体站常见）。

    只做最小修复：剥离 BOM/前导空白、把未转义的 & 转成 &amp;。
    清洗后仍失败则原样抛 ParseError，由调用方按来源隔离。
    """
    text = xml_text.lstrip("\ufeff \r\n\t")
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        return ET.fromstring(BARE_AMP_RE.sub("&amp;", text))


def parse_feed(xml_text: str, limit: int = 20) -> list[dict]:
    """解析 RSS 2.0 与 Atom，输出统一的 feed item 字典。"""
    root = _load_xml(xml_text)
    out: list[dict] = []
    for item in root.findall(".//item")[:limit]:
        link = (item.findtext("link") or "").strip()
        raw_body = item.findtext("description") or item.findtext("{*}encoded") or ""
        out.append({
            "url": link,
            "title": _strip_html(item.findtext("title") or ""),
            "published_at": _parse_date(item.findtext("pubDate") or item.findtext("date")),
            "summary": _strip_html(raw_body)[:3000],
            "author": _strip_html(item.findtext("author") or item.findtext("{*}creator"))[:200] or None,
            "code_blocks": _extract_code_blocks(raw_body),
        })
    if not out:
        for entry in root.findall(f".//{ATOM_NS}entry")[:limit]:
            link = ""
            for ln in entry.findall(f"{ATOM_NS}link"):
                if ln.get("rel") in (None, "alternate"):
                    link = ln.get("href") or ""
                    break
            content = entry.findtext(f"{ATOM_NS}content") or entry.findtext(f"{ATOM_NS}summary") or ""
            out.append({
                "url": link,
                "title": _strip_html(entry.findtext(f"{ATOM_NS}title") or ""),
                "published_at": _parse_date(entry.findtext(f"{ATOM_NS}updated")
                                           or entry.findtext(f"{ATOM_NS}published")),
                "summary": _strip_html(content)[:3000],
                "author": _strip_html(entry.findtext(f"{ATOM_NS}author/{ATOM_NS}name"))[:200] or None,
                "code_blocks": _extract_code_blocks(content),
            })
    return [o for o in out if o["url"] and o["title"]]


# ---------------------------------------------------------------- 适配器
def hn_frontpage(client: HttpClient, limit: int = 20) -> list[Record]:
    data = client.get_json(
        "https://hn.algolia.com/api/v1/search",
        params={"tags": "front_page", "hitsPerPage": limit})
    recs = []
    for hit in data.get("hits", []):
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        recs.append(Record(
            url=url, title=hit.get("title") or hit.get("story_title") or "untitled",
            published_at=hit.get("created_at"),
            summary=(hit.get("story_text") or "")[:2000] or None,
            author=hit.get("author"), category="news",
            tags=["hn", "tech"],
            metrics={"points": hit.get("points"), "comments": hit.get("num_comments")},
            extra={"hn_id": hit.get("objectID")}))
    return recs


def github_search(client: HttpClient, limit: int = 20) -> list[Record]:
    data = client.get_json(
        "https://api.github.com/search/repositories",
        params={"q": "stars:>3000 pushed:>2026-01-01", "sort": "stars",
                "order": "desc", "per_page": limit})
    recs = []
    for item in data.get("items", []):
        lic = (item.get("license") or {}).get("spdx_id")
        recs.append(Record(
            url=item["html_url"], title=item["full_name"],
            published_at=item.get("created_at"),
            summary=(item.get("description") or "")[:1000] or None,
            author=(item.get("owner") or {}).get("login"), category="opensource",
            tags=["github", "opensource"] + ([lic.lower()] if lic else []),
            metrics={"stars": item.get("stargazers_count"), "forks": item.get("forks_count"),
                     "open_issues": item.get("open_issues_count"), "license": lic},
            extra={"pushed_at": item.get("pushed_at"), "language": item.get("language")}))
    return recs


def github_releases(client: HttpClient, repos: list[str] | None = None, limit: int = 10) -> list[Record]:
    repos = repos or ["pytorch/pytorch", "huggingface/transformers", "ggml-org/llama.cpp",
                      "vllm-project/vllm", "openai/whisper", "microsoft/onnxruntime"]
    recs: list[Record] = []
    for repo in repos:
        try:
            items = parse_feed(client.get_text(f"https://github.com/{repo}/releases.atom"), limit=limit)
        except (FetchError, ET.ParseError):
            continue          # 单个仓库失败不影响其它仓库
        for it in items:
            recs.append(Record(
                url=it["url"], title=f"[{repo}] {it['title']}", published_at=it["published_at"],
                summary=it.get("summary"), category="opensource",
                tags=["github", "release", repo.split("/")[0]],
                extra={"repo": repo}))
    return recs


def hf_models(client: HttpClient, limit: int = 20) -> list[Record]:
    data = client.get_json("https://huggingface.co/api/models",
                           params={"sort": "trendingScore", "direction": -1, "limit": limit})
    recs = []
    for m in data:
        recs.append(Record(
            url=f"https://huggingface.co/{m.get('id')}", title=m.get("id") or "untitled",
            published_at=m.get("createdAt") or m.get("lastModified"),
            summary=(m.get("cardData") or {}).get("short_description") if isinstance(m.get("cardData"), dict) else None,
            author=m.get("author"), category="ai",
            tags=["huggingface", "model"] + ([m["pipeline_tag"]] if m.get("pipeline_tag") else []),
            metrics={"likes": m.get("likes"), "downloads": m.get("downloads"),
                     "trending": m.get("trendingScore")},
            extra={"gated": m.get("gated"), "private": m.get("private")}))
    return recs


def hf_datasets(client: HttpClient, limit: int = 15) -> list[Record]:
    data = client.get_json("https://huggingface.co/api/datasets",
                           params={"sort": "trendingScore", "direction": -1, "limit": limit})
    recs = []
    for d in data:
        recs.append(Record(
            url=f"https://huggingface.co/datasets/{d.get('id')}", title=d.get("id") or "untitled",
            published_at=d.get("createdAt") or d.get("lastModified"),
            author=d.get("author"), category="ai",
            tags=["huggingface", "dataset"],
            metrics={"likes": d.get("likes"), "downloads": d.get("downloads")},
            extra={"gated": d.get("gated")}))
    return recs


def hf_daily_papers(client: HttpClient, limit: int = 15) -> list[Record]:
    data = client.get_json("https://huggingface.co/api/daily_papers", params={"limit": limit})
    recs = []
    for row in data:
        paper = row.get("paper") or {}
        pid = paper.get("id") or row.get("id") or ""
        recs.append(Record(
            url=f"https://huggingface.co/papers/{pid}" if pid else "https://huggingface.co/papers",
            title=row.get("title") or paper.get("title") or "untitled",
            published_at=row.get("publishedAt"),
            summary=(row.get("summary") or "")[:1500] or None,
            author=(paper.get("authors") or [None])[0] if isinstance(paper.get("authors"), list) else None,
            category="research", tags=["paper", "arxiv", "hf-daily"],
            metrics={"comments": row.get("numComments"), "upvotes": paper.get("upvotes")},
            extra={"arxiv_id": paper.get("arxivId")}))
    return recs


def arxiv(client: HttpClient, limit: int = 20) -> list[Record]:
    url = ("http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.RO"
           f"&sortBy=submittedDate&sortOrder=descending&max_results={limit}")
    items = parse_feed(client.get_text(url), limit=limit)
    recs = []
    for it in items:
        recs.append(Record(url=it["url"], title=it["title"], published_at=it["published_at"],
                           summary=it.get("summary"), author=it.get("author"),
                           category="research", tags=["arxiv", "paper"]))
    return recs


BLOGS = [
    ("google_ai_blog", "Google AI Blog", "https://blog.google/technology/ai/rss/", ["ai", "blog"]),
    ("openai_news", "OpenAI News", "https://openai.com/news/rss.xml", ["ai", "blog"]),
    ("github_blog", "GitHub Blog", "https://github.blog/feed/", ["dev", "blog"]),
    ("hf_blog", "Hugging Face Blog", "https://huggingface.co/blog/feed.xml", ["ai", "blog"]),
    ("rust_blog", "Rust Blog", "https://blog.rust-lang.org/feed.xml", ["rust", "blog"]),
    ("pytorch_blog", "PyTorch Blog", "https://pytorch.org/feed.xml", ["ml", "blog"]),
]


def rss_official(client: HttpClient, limit: int = 10) -> list[Record]:
    recs: list[Record] = []
    for source_id, name, feed_url, tags in BLOGS:
        try:
            items = parse_feed(client.get_text(feed_url), limit=limit)
        except (FetchError, ET.ParseError):
            continue          # 单个博客失败不影响其它博客
        for it in items:
            recs.append(Record(url=it["url"], title=it["title"], published_at=it["published_at"],
                               summary=it.get("summary"), author=it.get("author"),
                               category="info", tags=tags + [source_id],
                               extra={"feed": feed_url, "feed_name": name}))
    return recs


# ---------------------------------------------------------------- 安全 / 黑客技术情报源
# 全部零凭证、直连可达（2026-11-19 实测：HttpClient trust_env=False 下可解析）。
# 说明：BleepingComputer / The Record / SecurityWeek 对非浏览器指纹返回 403/Cloudflare 挑战，
#       Exploit-DB 的 TLS 指纹被拦，Packet Storm 已无可用 RSS（/rss.xml 返回首页 HTML）；
#       以上站点不进直采清单，走 SKILL.md 的 P3 降级（Playwright/Camoufox）。
SEC_FEEDS = [
    ("thehackernews", "The Hacker News",
     "https://thehackernews.com/feeds/posts/default?alt=rss",
     ["hackernews", "threat-intel", "exploit"]),
    ("krebs", "Krebs on Security",
     "https://krebsonsecurity.com/feed/",
     ["cybercrime", "investigation"]),
    ("darkreading", "Dark Reading",
     "https://www.darkreading.com/rss.xml",
     ["enterprise", "security"]),
    ("hackread", "HackRead",
     "https://hackread.com/feed/",
     ["hacking", "breach"]),
    ("cyberscoop", "CyberScoop",
     "https://cyberscoop.com/feed/",
     ["policy", "security"]),
    ("cybersecuritydive", "Cybersecurity Dive",
     "https://www.cybersecuritydive.com/feeds/news/",
     ["industry", "security"]),
    ("securelist", "Securelist (Kaspersky)",
     "https://securelist.com/feed/",
     ["apt", "malware", "research"]),
    ("portswigger_research", "PortSwigger Research",
     "https://portswigger.net/research/rss",
     ["web-exploit", "research"]),
    ("seclists_fd", "Seclists Full Disclosure",
     "https://seclists.org/rss/fulldisclosure.rss",
     ["poc", "mailing-list"]),
    ("seebug_paper", "先知社区 paper.seebug.org",
     "https://paper.seebug.org/rss/",
     ["cn", "vuln-research"]),
    ("infosecurity_mag", "Infosecurity Magazine",
     "https://www.infosecurity-magazine.com/rss/news/",
     ["industry", "news"]),
    ("securityaffairs", "Security Affairs",
     "https://securityaffairs.com/feed",
     ["apt", "cybercrime", "news"]),
]


def sec_rss(client: HttpClient, limit: int = 10) -> list[Record]:
    """全球头部黑客/安全媒体 RSS；逐站故障隔离，单站失败只丢该站。

    单站超时压到 10s：The Hacker News 走 Blogger 托管，国内网络偶发 ConnectTimeout，
    压短超时可避免一个站点拖慢整轮采集（失败只影响该站，不影响同组其它来源）。
    """
    recs: list[Record] = []
    for source_id, name, feed_url, tags in SEC_FEEDS:
        try:
            items = parse_feed(client.get_text(feed_url, timeout=10), limit=limit)
        except (FetchError, ET.ParseError, OSError):
            continue          # 单站失败不影响同组其它站点
        for it in items:
            recs.append(Record(
                url=it["url"], title=it["title"], published_at=it["published_at"],
                summary=it.get("summary"), author=it.get("author"),
                category="security", tags=["security", "hacker"] + tags + [source_id],
                extra={"feed": feed_url, "feed_name": name, "site": source_id}))
    return recs


def github_advisories(client: HttpClient, limit: int = 20) -> list[Record]:
    """GitHub Security Advisories 公开 API（零凭证，带 CVE/CVSS/严重度）。"""
    data = client.get_json(
        "https://api.github.com/advisories",
        params={"per_page": limit},
        headers={"Accept": "application/vnd.github+json"})
    recs = []
    for a in data if isinstance(data, list) else []:
        ghsa = a.get("ghsa_id") or ""
        cve = a.get("cve_id")
        severity = (a.get("severity") or "unknown").lower()
        cvss = (a.get("cvss") or {}).get("score")
        recs.append(Record(
            url=a.get("html_url") or f"https://github.com/advisories/{ghsa}",
            title=f"[{severity.upper()}] {a.get('summary') or ghsa}",
            published_at=a.get("published_at"),
            summary=(a.get("description") or "")[:2000] or None,
            category="security",
            tags=["github", "advisory", "security", severity] + ([cve] if cve else []),
            metrics={"cvss": cvss, "cvss_vector": (a.get("cvss") or {}).get("vector_string")},
            external_key=f"ghsa:{ghsa}",
            extra={"ghsa_id": ghsa, "cve_id": cve, "severity": severity,
                   "cwe_ids": a.get("cwe_ids"),
                   "vulnerabilities": [
                       {"package": (v.get("package") or {}).get("name"),
                        "ecosystem": (v.get("package") or {}).get("ecosystem"),
                        "vulnerable_range": v.get("vulnerable_version_range"),
                        "patched": v.get("patched_versions")}
                       for v in (a.get("vulnerabilities") or [])][:10]}))
    return recs


def cisa_kev(client: HttpClient, limit: int = 20) -> list[Record]:
    """CISA 已知被利用漏洞目录（KEV）：真实在野利用证据，按加入日期倒序。"""
    payload = client.get_json(
        "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json")
    rows = payload.get("vulnerabilities") or []
    rows = sorted(rows, key=lambda v: v.get("dateAdded") or "", reverse=True)[:limit]
    recs = []
    for v in rows:
        cve = v.get("cveID") or ""
        recs.append(Record(
            url=f"https://nvd.nist.gov/vuln/detail/{cve}" if cve else "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
            title=f"[KEV] {cve} · {v.get('vendorProject')} {v.get('product')}".strip(),
            published_at=v.get("dateAdded"),
            summary=(f"{v.get('vulnerabilityName') or ''}\n\n{v.get('shortDescription') or ''}").strip()[:2000] or None,
            category="security",
            tags=["cisa", "kev", "exploited-in-wild", "security"]
                 + ([v["knownRansomwareCampaignUse"].lower()] if v.get("knownRansomwareCampaignUse") else []),
            metrics={"ransomware_use": v.get("knownRansomwareCampaignUse")},
            external_key=f"kev:{cve}",
            extra={"vendor": v.get("vendorProject"), "product": v.get("product"),
                   "required_action": v.get("requiredAction"), "due_date": v.get("dueDate")}))
    return recs


# ---------------------------------------------------------------- 受限安全源（两级回退）
# 这五站对「requests 默认 TLS 指纹」返回 403 / 挑战页。实测结论（2026-11-19）：
#   Exploit-DB      curl_cffi(impersonate=chrome) 直连 200  → 可解，无需代理
#   SecurityWeek    直连 403，经本地代理 200              → 需 SKILLKIT_PROXY
#   BleepingComputer / The Record  Cloudflare 托管挑战（要执行 JS）→ curl_cffi 与代理均 403，需真浏览器
#   Packet Storm    所有 feed 重定向到 packetstorm.news 的 tos 拦截页（返回 HTML）→ 需真浏览器
# 策略：每站先试 curl_cffi，再试代理；都失败则该站跳过（不影响其它站，也不伪造条目）。
# 第 5 个字段 browser_ok：无头浏览器能否取到 feed（2026-11-19 逐站实测）。
#   False 的站不再尝试浏览器，避免每次采集白等 20 秒；它们仍会先试前两级。
RESTRICTED_FEEDS = [
    ("exploitdb", "Exploit-DB", "https://www.exploit-db.com/rss.xml",
     ["exploit", "poc"], True),
    ("securityweek", "SecurityWeek", "https://www.securityweek.com/feed/",
     ["industry", "news"], True),
    ("bleepingcomputer", "BleepingComputer", "https://www.bleepingcomputer.com/feed/",
     ["malware", "news"], True),
    # Cloudflare "Just a moment" 挑战，无头浏览器同样 403；需人工/真浏览器指纹
    ("therecord", "The Record", "https://therecord.media/feed",
     ["news", "cybercrime"], False),
    # feed 全部重定向到 packetstorm.news 的 TOS 同意页（接口内 base64 回跳），未解
    ("packetstorm", "Packet Storm", "https://packetstormsecurity.com/feeds/news.xml",
     ["exploit", "advisory"], False),
]


def _fetch_impersonated(url: str, timeout: int = 20) -> str:
    """用浏览器 TLS 指纹抓取（curl_cffi）；未安装则抛 ImportError 由调用方降级。"""
    from curl_cffi import requests as curl_requests   # 可选依赖，缺失时走代理分支
    r = curl_requests.get(url, impersonate="chrome", timeout=timeout)
    if r.status_code >= 400:
        raise FetchError(f"HTTP {r.status_code}: {url}", r.status_code, "http")
    return r.text


def _default_browser_exe() -> str:
    """内置内核优先；可用 SKILLKIT_BROWSER_EXE 覆盖。"""
    exe = (os.environ.get("SKILLKIT_BROWSER_EXE") or "").strip()
    if exe:
        return exe
    return r"D:\00_skiill_ku\01_crawler\runtime\Playwright\chromium-1243\chrome-win64\chrome.exe"


class _BrowserFetch:
    """可复用的无头浏览器会话，专治 Cloudflare 托管挑战 / JS 渲染后的 feed。

    只在轻量通道全部失败时才创建；整个 sec_restricted 共用一个实例，启动一次。
    playwright 或内核缺失时 available=False，调用方退回「跳过该站」。
    """

    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._ctx = None
        self.available = False
        exe = _default_browser_exe()
        if not Path(exe).exists():
            return
        try:
            from playwright.sync_api import sync_playwright   # 可选依赖
        except ImportError:
            return
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                executable_path=exe, headless=True,
                args=["--disable-blink-features=AutomationControlled"])
            self._ctx = self._browser.new_context(
                user_agent=self.UA, locale="en-US",
                viewport={"width": 1366, "height": 900})
            self._ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            self.available = True
        except Exception:                      # noqa: BLE001 —— 内核损坏/端口占用等
            self.close()

    def get_text(self, url: str, timeout: int = 35000) -> str:
        """取页面文本；403 视为失败（挑战页无内容可用）。"""
        if not self.available:
            raise FetchError("浏览器通道不可用", None, "auth")
        page = self._ctx.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            if resp is not None and resp.status >= 400:
                raise FetchError(f"HTTP {resp.status}: {url}", resp.status, "http")
            return page.content()
        finally:
            page.close()

    def close(self) -> None:
        for obj, meth in ((self._ctx, "close"), (self._browser, "close"), (self._pw, "stop")):
            if obj is None:
                continue
            try:
                getattr(obj, meth)()
            except Exception:                  # noqa: BLE001
                pass
        self._ctx = self._browser = self._pw = None
        self.available = False


def sec_restricted(client: HttpClient, limit: int = 10) -> list[Record]:
    """受限站点采集：三级回退 —— curl_cffi 指纹 → 本地代理 → 无头浏览器，全败则跳过该站。

    返回的每条记录带 extra.via 标注实际通道（impersonate / proxy / browser），便于溯源。
    """
    from skillkit.http import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    proxy = (os.environ.get("SKILLKIT_PROXY") or "").strip()
    pc = HttpClient(policy=client.policy, proxy=proxy) if proxy else None

    recs: list[Record] = []
    pending: list[tuple[str, str, str, list[str]]] = []   # 前两级失败且浏览器可能可解的站
    for source_id, name, feed_url, tags, browser_ok in RESTRICTED_FEEDS:
        text, via = "", None
        try:
            text, via = _fetch_impersonated(feed_url), "impersonate"
        except Exception:                      # noqa: BLE001 —— 任何失败都退到下一级
            text = ""
        if not text and pc is not None:
            try:
                text, via = pc.get_text(feed_url, timeout=20), "proxy"
            except (FetchError, OSError):
                text = ""
        if not text:
            if browser_ok:
                pending.append((source_id, name, feed_url, tags))
            continue
        recs.extend(_feed_to_records(text, source_id, name, feed_url, tags, via, limit))

    if not pending:
        return recs

    browser = _BrowserFetch()                  # 启动一次，供所有残留站复用
    try:
        for source_id, name, feed_url, tags in pending:
            try:
                text = browser.get_text(feed_url)
            except Exception:                  # noqa: BLE001
                continue                       # 仍被拦：跳过，不伪造条目
            recs.extend(_feed_to_records(text, source_id, name, feed_url, tags, "browser", limit))
    finally:
        browser.close()
    return recs


def _feed_to_records(text: str, source_id: str, name: str, feed_url: str,
                     tags: list[str], via: str | None, limit: int) -> list[Record]:
    """把 feed 文本转成 Record；不是合法 feed（挑战页 HTML）时返回空列表。"""
    try:
        items = parse_feed(text, limit=limit)
    except ET.ParseError:
        return []
    recs: list[Record] = []
    for it in items:
        ctx = _context_tags(it.get("title"), it.get("summary"))
        recs.append(Record(
            url=it["url"], title=it["title"], published_at=it["published_at"],
            summary=it.get("summary"), author=it.get("author"),
            category="security", tags=["security", "hacker"] + tags + [source_id] + ctx,
            extra={"feed": feed_url, "feed_name": name, "site": source_id, "via": via,
                   "context_tags": ctx,
                   "code_blocks": it.get("code_blocks") or []}))
    return recs


# ---------------------------------------------------------------- 排障类来源
TROUBLESHOOT_QUERIES = [
    "403 in:title cloudflare",
    "playwright in:title blocked",
    "curl_cffi in:title 403",
    "reddit in:title blocked 403",
]

SO_TAGS = ["web-scraping", "playwright", "python-requests"]


def github_issues(client: HttpClient, limit: int = 8) -> list[Record]:
    """GitHub Issues 排障检索：按报错特征搜 issue，抓的是"别人踩过的坑"。

    未认证的 search API 限额 10 次/分钟，因此固定 4 条查询、单查询失败只丢该查询。
    """
    recs: list[Record] = []
    per_q = max(2, limit // len(TROUBLESHOOT_QUERIES))
    for q in TROUBLESHOOT_QUERIES:
        try:
            data = client.get_json(
                "https://api.github.com/search/issues",
                params={"q": f"{q} is:issue", "sort": "relevance", "order": "desc",
                        "per_page": per_q})
        except FetchError:
            continue
        for it in (data.get("items") or [])[:per_q]:
            if it.get("pull_request"):        # search/issues 会混入 PR，排障只留真 issue
                continue
            body = it.get("body") or ""
            title = (it.get("title") or "").strip()[:300]
            if not it.get("html_url") or not title:
                continue
            ctx = _context_tags(title, body)
            recs.append(Record(
                url=it["html_url"], title=title, published_at=it.get("created_at"),
                summary=body[:2000] or None, author=(it.get("user") or {}).get("login"),
                category="troubleshooting",
                tags=["github-issues", "troubleshooting"] + ctx,
                metrics={"comments": it.get("comments")},
                external_key=f"ghissue:{it.get('id')}",
                extra={"query": q, "state": it.get("state"), "context_tags": ctx,
                       "repo_url": (it.get("repository_url") or "").replace(
                           "https://api.github.com/repos/", "https://github.com/"),
                       "code_blocks": _extract_code_blocks(body)}))
    return recs


def stackoverflow(client: HttpClient, limit: int = 6) -> list[Record]:
    """Stack Overflow 排障问答（StackExchange 公开 API，无 key）。"""
    recs: list[Record] = []
    per_tag = max(2, limit // len(SO_TAGS))
    for tag in SO_TAGS:
        try:
            data = client.get_json(
                "https://api.stackexchange.com/2.3/questions",
                params={"site": "stackoverflow", "tagged": tag, "sort": "activity",
                        "order": "desc", "pagesize": per_tag, "filter": "withbody"})
        except FetchError:
            continue
        for it in (data.get("items") or [])[:per_tag]:
            body = it.get("body") or ""
            title = html.unescape(it.get("title") or "").strip()[:300]
            if not it.get("link") or not title:
                continue
            created = it.get("creation_date")
            published = (datetime.fromtimestamp(created, tz=timezone.utc).isoformat(
                timespec="seconds").replace("+00:00", "Z") if isinstance(created, int) else None)
            recs.append(Record(
                url=it["link"], title=title, published_at=published,
                summary=_strip_html(body)[:2000] or None,
                category="troubleshooting",
                tags=["stackoverflow", tag] + _context_tags(title, body),
                metrics={"score": it.get("score"), "answers": it.get("answer_count"),
                         "answered": it.get("is_answered")},
                external_key=f"so:{it.get('question_id')}",
                extra={"so_tag": tag,
                       "context_tags": _context_tags(title, body),
                       "code_blocks": _extract_code_blocks(body)}))
    return recs


def radar_zcl(client: HttpClient, limit: int = 30) -> list[Record]:
    payload = client.get_json("https://radar.zichuanlan.top/api/items",
                              params={"limit": limit, "offset": 0})
    recs = []
    for it in payload.get("items", []):
        recs.append(Record(
            url=it.get("url") or "", title=it.get("title") or "untitled",
            published_at=it.get("published_at"), summary=it.get("summary"),
            author=it.get("author"), category=it.get("category") or "other",
            tags=["resource-radar"] + ([it.get("category")] if it.get("category") else []),
            metrics={"score": it.get("score"), "ai_quality": it.get("ai_quality"),
                     "dup_count": it.get("dupCount"), "obtain": it.get("obtain")},
            external_key=f"zcl:{it.get('id')}",
            extra={"zcl_source_id": it.get("source_id"), "zcl_kind": it.get("kind"),
                   "zcl_id": it.get("id")}))
    return recs


# ---------------------------------------------------------------- 规格
def build_specs(client: HttpClient, limit: int = 20) -> list[SourceSpec]:
    """构造通道 A 的来源规格；每个来源相互独立。"""
    def mk(sid, name, stype, fn, aggregator=None, origin_extra_key=None):
        return SourceSpec(source_id=sid, source_name=name, source_type=stype,
                           channel="public", fetch=lambda fn=fn: fn(),
                           aggregator=aggregator, origin_extra_key=origin_extra_key)
    return [
        mk("hn_frontpage", "Hacker News 首页", "api", lambda: hn_frontpage(client, limit)),
        mk("github_search", "GitHub 公开仓库搜索", "api", lambda: github_search(client, limit)),
        mk("github_releases", "GitHub 公开 Release Atom", "atom", lambda: github_releases(client)),
        mk("hf_models", "Hugging Face 热门模型", "api", lambda: hf_models(client, limit)),
        mk("hf_datasets", "Hugging Face 热门数据集", "api", lambda: hf_datasets(client, max(5, limit // 2))),
        mk("hf_daily_papers", "Hugging Face Daily Papers", "api", lambda: hf_daily_papers(client, limit)),
        mk("arxiv", "arXiv 公开论文", "atom", lambda: arxiv(client, limit)),
        mk("rss_official", "官方技术博客 RSS/Atom", "rss", lambda: rss_official(client)),
        # 排障类来源：按报错特征检索，补足「遇到 403 时雷达查不到东西」的缺口。
        # 注：r/webscraping 无法直连（403），只能经 Folo 订阅后由 collect_folo.py 入库。
        mk("github_issues", "GitHub Issues 排障检索", "api",
           lambda: github_issues(client, max(4, limit // 2))),
        mk("stackoverflow", "Stack Overflow 排障问答", "api",
           lambda: stackoverflow(client, max(4, limit // 2))),
        # 安全 / 黑客技术情报：媒体 RSS 组 + GitHub 公告 + CISA 在野利用目录
        mk("sec_rss", "黑客与安全媒体 RSS（12 站）", "rss",
           lambda: sec_rss(client, max(5, limit // 2))),
        mk("sec_restricted", "受限安全源（Exploit-DB / SecurityWeek / BleepingComputer / The Record / Packet Storm）",
           "rss", lambda: sec_restricted(client, max(5, limit // 2))),
        mk("github_advisories", "GitHub Security Advisories", "api",
           lambda: github_advisories(client, limit)),
        mk("cisa_kev", "CISA 已知被利用漏洞目录（KEV）", "api",
           lambda: cisa_kev(client, max(5, limit // 2))),
        # 资源雷达是聚合器：origin_source 记录真实上游社区（zcl_source_id），不记渠道本身
        mk("radar_zcl", "资源雷达（公开只读 API）", "api", lambda: radar_zcl(client, limit),
           aggregator="radar.zichuanlan.top", origin_extra_key="zcl_source_id"),
    ]
