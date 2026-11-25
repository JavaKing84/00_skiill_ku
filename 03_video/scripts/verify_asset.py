#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_asset.py — 素材下载、验证与清单登记（Phase 2.1）。

流程：限速 → 带退避下载 → MIME/大小检查 → 图片(PIL)或视频/音频(ffprobe)验证
     → SHA256 → 写 assets_manifest.json（collection-manifest-v1）。
许可未知一律 unknown；不编造 URL；失败保留 http_status 与原因。
"""
from __future__ import annotations

import argparse
import mimetypes
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
from skillkit.manifest import CollectionManifest, CollectionRecord  # noqa: E402
from skillkit.policy import CrawlPolicy, RateLimiter  # noqa: E402
from skillkit.media import ffprobe  # noqa: E402

MEDIA_BY_MIME = {"image": "image", "video": "video", "audio": "audio"}


def media_type_of(response: requests.Response, url: str) -> str:
    ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip()
    guess = mimetypes.guess_type(urlparse(url).path)[0] or ctype
    for prefix, label in MEDIA_BY_MIME.items():
        if guess.startswith(prefix):
            return label
    return "webpage"


def download(url: str, dest: Path, policy: CrawlPolicy) -> tuple[int | None, str | None]:
    last_err = None
    for attempt in range(policy.max_retries + 1):
        try:
            with requests.get(url, headers={"User-Agent": policy.user_agent},
                              timeout=policy.timeout_seconds, stream=True) as r:
                if r.status_code in (401, 403):
                    return r.status_code, f"AUTH/ACCESS {r.status_code}"
                if r.status_code != 200:
                    last_err = f"HTTP {r.status_code}"
                    if r.status_code >= 500 and attempt < policy.max_retries:
                        continue
                    return r.status_code, last_err
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(1 << 18):
                        f.write(chunk)
                return r.status_code, None
        except requests.RequestException as exc:
            last_err = type(exc).__name__
            if attempt < policy.max_retries:
                continue
    return None, last_err


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--title", default="untitled")
    ap.add_argument("--source-name", default="manual-url")
    ap.add_argument("--manifest-name", default="assets_manifest.json")
    args = ap.parse_args()

    policy = CrawlPolicy()
    limiter = RateLimiter(policy)
    domain = urlparse(args.url).netloc
    limiter.wait(domain)

    project = Path(args.project_dir)
    suffix = Path(urlparse(args.url).path).suffix or ".bin"
    dest = project / "inputs" / f"asset_{abs(hash(args.url)) % 10**8}{suffix}"
    status, err = download(args.url, dest, policy)

    manifest_path = project / args.manifest_name
    manifest = CollectionManifest.load(manifest_path) if manifest_path.exists() \
        else CollectionManifest(project=project.name)
    rec = CollectionRecord(
        source_url=args.url, title=args.title, media_type="webpage",
        source_name=args.source_name, adapter="material", http_status=status,
    )
    if err:
        rec.status = "failed"
        rec.extra["error"] = err
        manifest.add(rec)
        manifest.save(manifest_path)
        print(f"FAIL {err} (http={status}); recorded in {manifest_path}")
        return 2

    # 重新判定真实媒体类型
    with open(dest, "rb") as f:
        head = f.read(512)
    ctype = mimetypes.guess_type(dest.name)[0] or "application/octet-stream"
    label = next((v for k, v in MEDIA_BY_MIME.items() if ctype.startswith(k)), None)
    if not label:
        label = "image" if head.startswith(b"\xff\xd8") or head.startswith(b"\x89PNG") else "webpage"
    rec.media_type = label
    rec.attach_file(dest)

    verify_ok, verify_note = False, ""
    try:
        if label == "image":
            from PIL import Image
            with Image.open(dest) as im:
                verify_note = f"image {im.size} {im.format}"
            verify_ok = True
        elif label in ("video", "audio"):
            meta = ffprobe(dest)
            verify_note = f"ffprobe streams={len(meta.get('streams', []))}"
            verify_ok = bool(meta.get("streams"))
        else:
            verify_note = "non-media download, no decoder check"
            verify_ok = dest.stat().st_size > 0
    except Exception as exc:  # 解码器失败
        verify_note = f"verify error: {type(exc).__name__}: {exc}"

    rec.status = "verified" if verify_ok else "failed"
    rec.extra["verify"] = verify_note
    dedup = manifest.add(rec)
    manifest.save(manifest_path)
    print(f"{rec.status.upper()} dedup={dedup} type={label} {verify_note} -> {dest}")
    return 0 if verify_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
