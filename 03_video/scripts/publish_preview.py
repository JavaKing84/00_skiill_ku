#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_preview.py — 发布 dry-run 预览（Phase 2.5）。

只生成 publish_preview.md，不调用任何发布接口，不产生公网动作。
账号标识脱敏；真实发布必须由用户另行明确批准。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def mask_account(account: str) -> str:
    if not account:
        return "(未指定)"
    if len(account) <= 4:
        return account[0] + "***"
    return account[:2] + "***" + account[-2:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--platform", required=True, help="如 douyin/xiaohongshu/bilibili")
    ap.add_argument("--account", default="")
    ap.add_argument("--title", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--tags", default="", help="逗号分隔")
    ap.add_argument("--cover", default="")
    ap.add_argument("--scheduled-at", default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    video = Path(args.video)
    if not video.exists():
        print(f"FAIL: video missing {video}")
        return 2

    payload = {
        "mode": "DRY_RUN_ONLY",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "platform": args.platform,
        "account_masked": mask_account(args.account),
        "video": str(video),
        "video_bytes": video.stat().st_size,
        "title": args.title,
        "description": args.description,
        "tags": [t.strip() for t in args.tags.split(",") if t.strip()],
        "cover": args.cover or "(默认首帧)",
        "scheduled_at": args.scheduled_at or "(立即，待人工批准)",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    (out.with_suffix(".json")).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        "# 发布预览（DRY-RUN，未公开发布）",
        f"- 生成时间：{payload['generated_at']}",
        f"- 平台：{payload['platform']}　账号（脱敏）：{payload['account_masked']}",
        f"- 视频：`{payload['video']}`（{payload['video_bytes']} bytes）",
        f"- 标题：{payload['title']}",
        f"- 简介：{payload['description'] or '(空)'}",
        f"- 标签：{', '.join(payload['tags']) or '(空)'}",
        f"- 封面：{payload['cover']}",
        f"- 计划时间：{payload['scheduled_at']}",
        "",
        "> 本文件由 publish_preview.py 生成，未调用任何发布接口。",
        "> 真实发布需要用户明确批准，并改走 channel-publish 的正式流程。",
    ]
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"DRY-RUN preview -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
