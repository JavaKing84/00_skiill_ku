"""跨来源规范化键：让同一 GitHub 项目/同一原帖在不同采集渠道间可关联。

设计原则：
- 只做保守的、可解释的归一化，不做模糊匹配（模糊判断交给分析层）。
- GitHub 仓库收敛到 owner/repo 主键，子页面（/tree、/blob、/releases）视为同一项目。
- 去除常见跟踪参数（utm/spm/ref/from 等），保留有语义的查询参数。
"""
from __future__ import annotations

from urllib.parse import urlsplit, parse_qsl, urlunsplit

TRACKING_PREFIXES = ("utm_", "spm", "ref", "from", "source", "campaign",
                     "share", "shareid", "fbclid", "gclid", "mc_")
TRACKING_EXACT = {"ref", "ref_src", "ref_url", "from", "source", "spm"}


def canonical_url_key(url: str | None) -> str:
    """返回跨来源可比对的规范化 URL 键；无法解析时返回原值小写。"""
    if not url:
        return ""
    raw = url.strip()
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw.lower()
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = parts.path.rstrip("/")

    # GitHub 仓库收敛：/owner/repo 之后的子路径全部截掉
    if host == "github.com":
        segs = [s for s in path.split("/") if s]
        if len(segs) >= 2 and segs[0] not in {"topics", "trending", "marketplace", "orgs", "search"}:
            path = "/" + "/".join(segs[:2])

    # 过滤跟踪参数，其余保留并排序
    kept = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        kl = k.lower()
        if kl in TRACKING_EXACT or any(kl.startswith(p) for p in TRACKING_PREFIXES):
            continue
        kept.append((kl, v))
    query = "&".join(f"{k}={v}" for k, v in sorted(kept))
    return urlunsplit(("https", host, path, query, "")).removeprefix("https://")
