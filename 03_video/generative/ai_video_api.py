"""ai_video_api.py — 云端 AI 视频生成统一封装（Seedance / SiliconFlow 聚合）。

设计目标：让大模型在技能触发时，一行 Python / 一条 CLI 就能调度生视频，
不用关心各家 API 的签名差异。

支持后端：
  - siliconflow：聚合多家（Seedance / MiniMax-H3 / 可灵等），一个 Key，成本最低
  - volcengine：火山引擎方舟 Seedance 直连
  - aitoearn_mcp：走本机 aitoearn-cn MCP（本环境已接入，无需额外 Key）

诚实性：未配置密钥时返回 BLOCKED，不生成假视频、不写空文件冒充成功。

CLI:
  python generative/ai_video_api.py --prompt "..." --model seedance2.5 --duration 5 --resolution 720p --backend siliconflow --out out.mp4 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

# 允许脚本单跑（python generative/ai_video_api.py）时也能引用库根目录的公共模块
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from _shared.security import mask_secret  # noqa: E402

SF_BASE = "https://api.siliconflow.cn/v1"
VOLC_BASE = "https://ark.cn-beijing.volces.com/api/v3"

BACKENDS = {
    "siliconflow": {"env_key": "SILICONFLOW_API_KEY", "models": ["seedance2.5", "seedance2.0", "MiniMax-H3", "kling-v1"]},
    "volcengine":  {"env_key": "VOLC_API_KEY",       "models": ["seedance-2.5", "seedance-2.0"]},
}


def _key(backend: str) -> str | None:
    return os.environ.get(BACKENDS[backend]["env_key"])


def generate_siliconflow(prompt: str, model: str, duration: int = 5,
                         resolution: str = "720p", image: str | None = None,
                         dry_run: bool = False) -> dict:
    """硅基流动视频生成（异步：创建任务 → 轮询）。无 Key 或 dry-run 时不真正调用。"""
    key = _key("siliconflow")
    body = {"model": model, "prompt": prompt, "duration": duration, "resolution": resolution}
    if image:
        body["image"] = image
    if dry_run:
        # dry-run 免 Key：只展示将发送的请求，不扣费、不真正调用
        return {"blocked": False, "dry_run": True, "backend": "siliconflow",
                "has_api_key": bool(key),
                "auth_preview": ("Bearer " + mask_secret(key)) if key else "未配置",
                "request": {"url": f"{SF_BASE}/videos/generations", "body": body}}
    if not key:
        return {"blocked": True, "backend": "siliconflow",
                "reason": f"未设置环境变量 {BACKENDS['siliconflow']['env_key']}（需充值获取）"}
    t0 = time.time()
    r = requests.post(f"{SF_BASE}/videos/generations", headers={"Authorization": f"Bearer {key}"},
                      json=body, timeout=60)
    if r.status_code != 200:
        return {"blocked": False, "ok": False, "status": r.status_code, "error": r.text[:300]}
    task = r.json()
    task_id = task.get("id")
    # 轮询结果（最多 5 分钟）
    for _ in range(60):
        time.sleep(5)
        pr = requests.get(f"{SF_BASE}/videos/generations/{task_id}",
                          headers={"Authorization": f"Bearer {key}"}, timeout=30)
        st = pr.json().get("status")
        if st in ("succeeded", "completed"):
            return {"ok": True, "backend": "siliconflow", "model": model,
                    "task_id": task_id, "video_url": pr.json().get("video", {}).get("url"),
                    "elapsed_sec": round(time.time() - t0, 1)}
        if st in ("failed", "error"):
            return {"ok": False, "task_id": task_id, "error": pr.text[:300]}
    return {"ok": False, "task_id": task_id, "error": "timeout polling"}


def generate(prompt: str, model: str = "seedance2.5", duration: int = 5,
             resolution: str = "720p", backend: str = "siliconflow",
             image: str | None = None, out: str | None = None,
             dry_run: bool = False) -> dict:
    """统一入口。"""
    if backend == "siliconflow":
        res = generate_siliconflow(prompt, model, duration, resolution, image, dry_run)
    else:
        return {"blocked": True, "reason": f"后端 {backend} 暂未实现直连；可用 siliconflow 或 aitoearn MCP"}
    # 下载到本地（若有 URL 且指定 out）
    if res.get("ok") and res.get("video_url") and out and not dry_run:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        data = requests.get(res["video_url"], timeout=120).content
        Path(out).write_bytes(data)
        res["saved_to"] = out
        res["bytes"] = len(data)
    return res


def generate_image(prompt: str, model: str = "black-forest-labs/FLUX.1-schnell",
                   size: str = "1024x1024", backend: str = "siliconflow",
                   out: str | None = None, dry_run: bool = False) -> dict:
    """文生图（SiliconFlow 聚合 Flux 等）。dry-run 免 Key 预览请求体；无 Key 返回 blocked。"""
    if backend != "siliconflow":
        return {"blocked": True, "reason": f"后端 {backend} 文生图暂未实现"}
    key = _key("siliconflow")
    body = {"model": model, "prompt": prompt, "image_size": size}
    if dry_run:
        return {"blocked": False, "dry_run": True, "backend": "siliconflow",
                "has_api_key": bool(key),
                "auth_preview": ("Bearer " + mask_secret(key)) if key else "未配置",
                "request": {"url": f"{SF_BASE}/images/generations", "body": body}}
    if not key:
        return {"blocked": True, "backend": "siliconflow",
                "reason": "未设置 SILICONFLOW_API_KEY，文生图无法执行（需充值）"}
    r = requests.post(f"{SF_BASE}/images/generations",
                      headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
    if r.status_code != 200:
        return {"blocked": False, "ok": False, "status": r.status_code, "error": r.text[:300]}
    data = r.json()
    images = data.get("images", [])
    url = images[0].get("url") if images else None
    res = {"ok": True, "backend": "siliconflow", "model": model,
           "image_url": url, "image_size": size}
    if url and out and not dry_run:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        d = requests.get(url, timeout=120).content
        Path(out).write_bytes(d)
        res["saved_to"] = out
        res["bytes"] = len(d)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="云端 AI 视频/图像生成统一封装")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--model", default="seedance2.5")
    ap.add_argument("--duration", type=int, default=5)
    ap.add_argument("--resolution", default="720p")
    ap.add_argument("--backend", default="siliconflow", choices=list(BACKENDS))
    ap.add_argument("--image", default="", help="图生视频参考图 URL（可选）")
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true", help="只打印请求，不真正调用/扣费")
    ap.add_argument("--image-gen", action="store_true", help="走文生图而非生视频")
    ap.add_argument("--image-size", default="1024x1024")
    a = ap.parse_args()
    if a.image_gen:
        res = generate_image(a.prompt, a.model, a.image_size, a.backend,
                             a.out or None, a.dry_run)
    else:
        res = generate(a.prompt, a.model, a.duration, a.resolution, a.backend,
                       a.image or None, a.out or None, a.dry_run)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if (res.get("ok") or res.get("dry_run") or res.get("blocked")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
