#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
material_crawler.py — 素材检索与本地化（P0-P5 最小闭环）

用法:
  python material_crawler.py --q "night city" --videos 3 --images 2 --orientation portrait
  python material_crawler.py --q "咖啡拉花" --videos 2 --images 4 --out "E:\\Trae_Video_Workspace\\inputs\\咖啡拉花"

设计依据:
  D:\\00_skiill_ku\\01_crawler\\SKILL.md
  D:\\00_skiill_ku\\01_crawler\\skills\\web-scraping\\05_failure_taxonomy.md
  D:\\00_skiill_ku\\01_crawler\\skills\\web-scraping\\06_code_templates.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from PIL import Image

try:
    import imageio_ffmpeg
except ImportError:  # 允许没有 ffmpeg 时降级
    imageio_ffmpeg = None


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
BASE_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
TIMEOUT = 30


class CrawlerError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Candidate:
    kind: str  # image / video
    title: str
    url: str
    page_url: str
    provider: str
    license: str
    attribution: str = ""
    width: int = 0
    height: int = 0
    duration_s: float | None = None
    thumb: str = ""


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def jitter(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))


def backoff(attempt: int, base: float = 2.0, cap: float = 60.0) -> float:
    delay = min(cap, base * (2 ** attempt)) * random.uniform(0.6, 1.4)
    time.sleep(delay)
    return delay


class Fetcher:
    """优先 requests；403/空响应时降级 curl.exe（本地武器库的直连思路）。"""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(BASE_HEADERS)

    def _curl(self, url: str, referer: str | None, output: str | None = None) -> bytes:
        if not shutil.which("curl.exe") and not shutil.which("curl"):
            raise CrawlerError("F-02", "curl 不可用，无法降级")
        curl = shutil.which("curl.exe") or shutil.which("curl")
        cmd = [curl, "-sS", "-L", "--max-time", str(TIMEOUT), "-A", UA]
        if referer:
            cmd += ["-e", referer]
        if output:
            cmd += ["-o", output]
        cmd.append(url)
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            raise CrawlerError("F-02", f"curl 失败: {proc.stderr.decode('utf-8', 'replace')[:200]}")
        return b"" if output else proc.stdout

    def get(self, url: str, referer: str | None = None, retries: int = 2,
            params: dict[str, Any] | None = None, accept: str | None = None) -> requests.Response:
        last_err = ""
        for attempt in range(retries + 1):
            headers = {"Referer": referer} if referer else {}
            if accept:
                headers["Accept"] = accept
            try:
                resp = self.session.get(url, headers=headers, params=params,
                                        timeout=TIMEOUT, allow_redirects=True)
            except requests.RequestException as exc:
                last_err = f"网络异常: {exc}"
                if attempt < retries:
                    backoff(attempt)
                    continue
                raise CrawlerError("F-01", last_err)

            if resp.status_code == 200 and len(resp.content) > 0:
                return resp
            if resp.status_code == 429:
                wait = resp.headers.get("retry-after")
                delay = float(wait) if wait and wait.isdigit() else backoff(attempt)
                last_err = f"429 限流，等待 {delay:.1f}s（A-02）"
                log(last_err)
                if attempt < retries:
                    continue
                raise CrawlerError("F-02", last_err)
            if resp.status_code in (401, 403):
                last_err = f"403 防盗链/风控（F-02），referer={referer or '无'}"
                if attempt == 0 and not referer:
                    log(last_err + " -> 补 Referer 重试")
                    continue
                if attempt < retries:
                    jitter(2, 5)
                    continue
                raise CrawlerError("F-02", last_err)
            if resp.status_code >= 500:
                last_err = f"{resp.status_code} 服务端错误（F-02）"
                if attempt < retries:
                    backoff(attempt)
                    continue
                raise CrawlerError("F-02", last_err)
            raise CrawlerError("F-03", f"HTTP {resp.status_code}: {url}")

        raise CrawlerError("F-02", last_err or "未知请求失败")

    def get_text(self, url: str, referer: str | None = None) -> str:
        try:
            return self.get(url, referer=referer).text
        except CrawlerError:
            raw = self._curl(url, referer)
            if not raw:
                raise
            return raw.decode("utf-8", "replace")

    def download(self, url: str, dest: Path, referer: str | None = None) -> str:
        """流式下载；返回 content-type。失败时降级 curl。"""
        part = dest.with_suffix(dest.suffix + ".part")
        headers = dict(BASE_HEADERS)
        if referer:
            headers["Referer"] = referer
        try:
            with self.session.get(url, headers=headers, timeout=TIMEOUT, stream=True) as resp:
                if resp.status_code != 200:
                    raise CrawlerError("F-02", f"下载 HTTP {resp.status_code}")
                content_type = resp.headers.get("content-type", "")
                total = 0
                with open(part, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            fh.write(chunk)
                            total += len(chunk)
                if total <= 0:
                    raise CrawlerError("F-03", "下载得到 0 字节（F-03 软拦截/空文件）")
            os.replace(part, dest)
            return content_type
        except (requests.RequestException, CrawlerError):
            if part.exists():
                part.unlink(missing_ok=True)
            self._curl(url, referer, output=str(dest))
            if not dest.exists() or dest.stat().st_size <= 0:
                raise CrawlerError("F-02", f"curl 下载失败: {url}")
            return ""


def normalize_url(raw: str) -> str:
    return (
        (raw or "")
        .strip()
        .strip("<>")
        .replace("%5F", "_")
        .replace("%28", "(")
        .replace("%29", ")")
        .replace("%2C", ",")
    )


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug


def search_images(fetcher: Fetcher, q: str, n: int, orientation: str,
                  allow_wikimedia: bool, notes: list[str]) -> list[Candidate]:
    params = {
        "q": q,
        "page_size": "20",
        "license": "cc0,by",
        "size": "large",
        "source": "flickr,rawpixel",
    }
    if allow_wikimedia:
        params.pop("source", None)  # 允许 Wikimedia/StockSnap 时走全量源，靠 Referer 破解防盗链
    if orientation == "portrait":
        params["aspect_ratio"] = "tall"
    elif orientation == "landscape":
        params["aspect_ratio"] = "wide"

    def call(extra: dict[str, str]) -> dict[str, Any]:
        try:
            resp = fetcher.get(
                "https://api.openverse.org/v1/images/",
                params={**params, **extra},
                accept="application/json",
            )
            return resp.json()
        except CrawlerError as exc:
            notes.append(f"图片检索失败 {exc.code}: {exc.message}")
            return {}
        except Exception as exc:  # JSON 解析失败时留证据
            notes.append(f"图片检索返回非 JSON（F-03）: {exc}")
            return {}

    data = call({})
    if not data.get("results") and params.get("source"):
        notes.append("指定图库（flickr,rawpixel）无结果，放宽到全部图库重试一次。")
        params.pop("source", None)
        data = call({})

    out: list[Candidate] = []
    blocked = {"wikimedia", "stocksnap"}
    for item in data.get("results", []):
        provider = item.get("provider") or item.get("source") or "openverse"
        if provider in blocked and not allow_wikimedia:
            continue
        direct = normalize_url(item.get("url", ""))
        if not direct:
            continue
        out.append(Candidate(
            kind="image",
            title=item.get("title") or "未命名图片",
            url=direct,
            page_url=item.get("foreign_landing_url") or "",
            provider=provider,
            license=(item.get("license") or "").upper(),
            attribution=item.get("attribution") or "",
            width=int(item.get("width") or 0),
            height=int(item.get("height") or 0),
            thumb=direct,
        ))
        if len(out) >= n:
            break
    if not out:
        notes.append("图片没有匹配结果（F-03），可换同义词或去掉风格词。")
    return out


def video_slug_candidates(q: str) -> list[str]:
    base = slugify(q)
    if not base:
        return []
    words = [w for w in base.split("-") if len(w) >= 3]
    return list(dict.fromkeys([base, "-".join(reversed(words)), *words]))


def search_videos(fetcher: Fetcher, q: str, n: int, notes: list[str]) -> list[Candidate]:
    candidates = video_slug_candidates(q)
    if not candidates:
        notes.append("视频检索需要英文关键词，已跳过。")
        return []

    html = ""
    slug = ""
    links: list[tuple[str, str]] = []
    link_re = re.compile(r'href="(/free-stock-video/[a-z0-9%-]+-(\d+)/)"')
    for candidate in candidates:
        try:
            html = fetcher.get_text(f"https://mixkit.co/free-stock-video/{candidate}/")
        except CrawlerError:
            continue
        seen: set[str] = set()
        links = []
        for match in link_re.finditer(html):
            path, vid = match.group(1), match.group(2)
            if vid in seen:
                continue
            seen.add(vid)
            links.append((urljoin("https://mixkit.co", path), vid))
            if len(links) >= n * 3:
                break
        if links:
            slug = candidate
            break

    if not links:
        notes.append(f"Mixkit 没有匹配分类（已尝试 {' / '.join(candidates)}），可换英文同义词。")
        return []

    out: list[Candidate] = []
    for page_url, vid in links:
        try:
            page = fetcher.get_text(page_url, referer="https://mixkit.co/")
        except CrawlerError:
            continue

        mp4s = re.findall(r'https://assets\.mixkit\.co/videos/[^"\s<>]+\.mp4', page)
        if not mp4s:
            notes.append(f"Mixkit {vid} 详情页没有 mp4 直链（F-25），跳过。")
            continue
        # 优先高码率档位
        mp4s = list(dict.fromkeys(mp4s))
        mp4s.sort(key=lambda u: int(re.search(r"-(\d+)\.mp4", u).group(1))
                  if re.search(r"-(\d+)\.mp4", u) else 0, reverse=True)
        mp4 = mp4s[0]

        og = re.search(r'property="og:title" content="([^"]+)"', page)
        title = (og.group(1) if og else "").replace(" - Free Stock Video", "").strip() or f"Mixkit {vid}"
        poster = re.search(r'poster="([^"]+)"', page)
        dur = re.search(r"(?:Duration|duration)[^0-9]{0,120}(\d{1,2}):(\d{2})", page)
        duration_s = int(dur.group(1)) * 60 + int(dur.group(2)) if dur else None
        best = (0, 0)
        for w, h in re.findall(r"(\d{3,4})x(\d{3,4})", page):
            if int(w) * int(h) > best[0] * best[1]:
                best = (int(w), int(h))

        out.append(Candidate(
            kind="video",
            title=title,
            url=mp4,
            page_url=page_url,
            provider="mixkit",
            license="Mixkit Free License",
            width=best[0],
            height=best[1],
            duration_s=duration_s,
            thumb=poster.group(1) if poster else "",
        ))
        if len(out) >= n:
            break

    if not out:
        notes.append("视频详情页没有可下载的 mp4（F-17/F-25）。")
    return out


def md5_of(path: Path) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ffprobe_media(path: Path) -> dict[str, Any]:
    if imageio_ffmpeg is None:
        return {"ok": False, "error": "imageio-ffmpeg 未安装，无法校验视频"}
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    text = proc.stderr
    duration = 0.0
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if match:
        duration = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    width = height = 0
    vm = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", text)
    if vm:
        width, height = int(vm.group(1)), int(vm.group(2))
    return {
        "ok": "Video:" in text,
        "duration_s": round(duration, 3),
        "width": width,
        "height": height,
        "has_audio": "Audio:" in text,
        "error": "" if "Video:" in text else "没有视频流（F-17）",
    }


def image_probe(path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as img:
            width, height = img.size
            fmt = img.format or path.suffix.lstrip(".").upper()
        return {"ok": width > 0 and height > 0, "width": width, "height": height, "format": fmt}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"图片校验失败: {exc}"}


def safe_name(text: str, limit: int = 40) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", text).strip(" ._")
    return cleaned[:limit] or "素材"


def load_manifest(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            path.rename(path.with_suffix(".corrupt.json"))
    return {"items": [], "updated_at": ""}


def save_manifest(path: Path, data: dict[str, Any]) -> None:
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def default_out_dir(q: str) -> Path:
    base = Path(r"E:\Trae_Video_Workspace\inputs")
    if not base.exists():
        base = Path.cwd() / "inputs"
    return base / f"{safe_name(q)}_{datetime.now():%Y%m%d}"


def convert_image_format(src: Path, target_ext: str) -> Path:
    """把图片转成目标格式；WebP/PNG 带透明通道时用白底合成 JPG。"""
    target = src.with_suffix(target_ext)
    with Image.open(src) as img:
        if target_ext == ".jpg":
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                canvas = Image.new("RGB", rgba.size, (255, 255, 255))
                canvas.paste(rgba, mask=rgba.split()[-1])
                out = canvas
            else:
                out = img.convert("RGB")
            out.save(target, "JPEG", quality=92)
        elif target_ext == ".webp":
            out = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
            out.save(target, "WEBP", quality=92)
        else:
            img.save(target)
    if target != src and src.exists():
        src.unlink()
    return target


def download_candidates(
    fetcher: Fetcher,
    candidates: list[Candidate],
    out_dir: Path,
    q: str,
    orientation: str,
    image_format: str = "jpg",
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    manifest_path = out_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    known_md5 = {item.get("md5") for item in manifest["items"] if item.get("md5")}
    files: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for index, cand in enumerate(candidates, 1):
        try:
            jitter(0.8, 2.0)
            out_dir.mkdir(parents=True, exist_ok=True)
            ext = ".mp4" if cand.kind == "video" else ".jpg"
            name = f"{safe_name(q)}_{'竖屏' if orientation == 'portrait' else '横屏' if orientation == 'landscape' else '素材'}_{cand.kind == 'video' and '视频' or '图片'}_{index:02d}{ext}"
            dest = out_dir / name
            if dest.exists() and dest.stat().st_size > 0:
                log(f"[跳过] 已存在 {dest.name}")
            else:
                log(f"[下载] {cand.kind} {cand.title[:50]}")
                fetcher.download(cand.url, dest, referer=cand.page_url or None)

            if cand.kind == "video":
                probe = ffprobe_media(dest)
                if not probe.get("ok"):
                    dest.unlink(missing_ok=True)
                    raise CrawlerError("F-17", probe.get("error", "视频校验失败"))
                source_format = "MP4"
            else:
                probe = image_probe(dest)
                if not probe.get("ok"):
                    dest.unlink(missing_ok=True)
                    raise CrawlerError("F-17", probe.get("error", "图片校验失败"))
                source_format = (probe.get("format") or "").upper()
                # 抖音图片只收 jpg/jpeg/png/bmp，默认统一转 JPG。
                if image_format in ("jpg", "webp"):
                    want = "JPEG" if image_format == "jpg" else "WEBP"
                    want_ext = "." + image_format
                    if source_format != want or dest.suffix.lower() != want_ext:
                        dest = convert_image_format(dest, want_ext)
                        probe = image_probe(dest)
                        log(f"  [转码] -> {dest.name}（{source_format} -> {want}）")
                else:
                    # auto：按真实格式落盘，避免扩展名与内容不一致。
                    ext_map = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}
                    target_ext = ext_map.get(source_format)
                    if target_ext and dest.suffix.lower() != target_ext:
                        new_dest = dest.with_suffix(target_ext)
                        new_dest.unlink(missing_ok=True)
                        dest.rename(new_dest)
                        log(f"  [重命名] {dest.name} -> {new_dest.name}（实际格式 {source_format}）")
                        dest = new_dest

            digest = md5_of(dest)
            if digest in known_md5:
                dest.unlink(missing_ok=True)
                log(f"[去重] MD5 重复，已删除 {dest.name}")
                continue
            known_md5.add(digest)

            record = {
                "file": dest.name,
                "abs_path": str(dest.resolve()),
                "kind": cand.kind,
                "title": cand.title,
                "source_url": cand.url,
                "page_url": cand.page_url,
                "provider": cand.provider,
                "license": cand.license,
                "attribution": cand.attribution,
                "size": dest.stat().st_size,
                "md5": digest,
                "width": probe.get("width", 0),
                "height": probe.get("height", 0),
                "duration_s": probe.get("duration_s"),
                "has_audio": probe.get("has_audio"),
                "format": probe.get("format") or source_format,
                "source_format": source_format,
                "downloaded_at": datetime.now().isoformat(timespec="seconds"),
            }
            files.append(record)
            manifest["items"].append(record)
            log(f"  -> {dest.name} {record['size'] / 1024 / 1024:.1f}MB "
                f"{record['width']}x{record['height']} audio={record['has_audio']}")
        except CrawlerError as exc:
            failures.append({"title": cand.title, "url": cand.url, "code": exc.code, "reason": exc.message})
            log(f"[失败] {exc.code} {cand.title[:40]} :: {exc.message}")
        except Exception as exc:  # noqa: BLE001
            failures.append({"title": cand.title, "url": cand.url, "code": "F-17", "reason": str(exc)})
            log(f"[失败] F-17 {cand.title[:40]} :: {exc}")

    save_manifest(manifest_path, manifest)
    return files, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="P0-P5 素材检索与本地下载")
    parser.add_argument("--q", required=True, help="关键词（中文会原样使用；视频建议英文）")
    parser.add_argument("--name", default="", help="文件名/目录词条，默认使用 --q；例如 --q \"night city\" --name \"城市夜景\"")
    parser.add_argument("--videos", type=int, default=3, help="视频数量，默认 3")
    parser.add_argument("--images", type=int, default=2, help="图片数量，默认 2")
    parser.add_argument("--orientation", choices=["portrait", "landscape", "any"], default="portrait")
    parser.add_argument("--image-format", choices=["jpg", "webp", "auto"], default="jpg",
                        help="图片落盘格式；默认 jpg（抖音兼容），auto 保留源格式")
    parser.add_argument("--out", default="", help="输出目录；默认 E:\\Trae_Video_Workspace\\inputs\\<关键词>_<日期>")
    parser.add_argument("--allow-wikimedia", action="store_true", help="允许 Wikimedia/StockSnap（会补 Referer）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    out_dir = Path(args.out) if args.out else default_out_dir(args.name or args.q)
    notes: list[str] = []
    fetcher = Fetcher()
    label = args.name or args.q

    log("【P0】情报：图片=Openverse(flickr/rawpixel)，视频=Mixkit 详情页 mp4")
    images = search_images(fetcher, args.q, args.images, args.orientation, args.allow_wikimedia, notes) if args.images else []
    videos = search_videos(fetcher, args.q, args.videos, notes) if args.videos else []

    profile = {
        "站点": "Openverse + Mixkit",
        "渲染层": "独立 API / SSR 页面",
        "数据位置": "Openverse JSON API；Mixkit 详情页 mp4",
        "需登录": "否",
        "签名参数": "无",
        "已知防护": "Openverse 匿名限流；Wikimedia/StockSnap 防盗链",
        "预估": f"图片 {len(images)} 条，视频 {len(videos)} 条",
    }
    log(f"【P0】画像卡：{profile}")

    files, failures = download_candidates(
        fetcher, images + videos, out_dir, label, args.orientation, args.image_format
    )

    result = {
        "ok": bool(files),
        "query": args.q,
        "out_dir": str(out_dir.resolve()),
        "profile": profile,
        "files": files,
        "failures": failures,
        "notes": notes,
        "manifest": str((out_dir / "manifest.json").resolve()),
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n输出目录: {out_dir.resolve()}")
        print(f"成功 {len(files)} 个，失败 {len(failures)} 个")
        for item in files:
            print(f"- {item['abs_path']}  {item['size']/1024/1024:.2f}MB  "
                  f"{item['width']}x{item['height']}  audio={item['has_audio']}  {item['license']}")
        for item in failures:
            print(f"- [FAIL {item['code']}] {item['title'][:40]} :: {item['reason']}")
        if notes:
            print("备注: " + "；".join(notes))

    return 0 if files else 1


if __name__ == "__main__":
    sys.exit(main())
