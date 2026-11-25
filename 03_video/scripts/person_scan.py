#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""person_scan.py — 画面人物检索/筛选（纯 CPU，ONNXRuntime-YuNet + OpenCV-SFace）

解决：whisper 只能识别"谁在说话"，不能识别"画面里出现了谁"。
本脚本按窗口扫描视频画面，判定每段是否出现目标主角 / 黑名单人物，输出可被
material_retrieve.py、quality_check_all.py 直接消费的 CSV。

依赖：onnxruntime + opencv-python + numpy + ffmpeg（抽帧）
模型：models/face_detection_yunet_2023mar.onnx、models/face_recognition_sface_2021dec.onnx
      （下载地址见 SKILL.md / tech_radar.md §10）

为什么不用 cv2.FaceDetectorYN：本机 OpenCV 5.1.0 的新 graph engine 在 detect() 上返回
retval=1 但人脸矩阵为空（已实测），因此改为 onnxruntime 直接跑 YuNet 并自行解码；
人脸对齐与特征仍用 cv2.FaceRecognizerSF（SFace）。

用法：
  # 1) 用已知镜头自动裁脸建参考库（人工只需给脸贴名字）
  python person_scan.py --build-gallery --spec faces_seed.json --video-dir <素材目录> --gallery <头像目录>

  # 2) 扫描
  python person_scan.py --video 导剪002.mp4 --start 1620 --end 1700 \
      --gallery D:/00_skiill_ku/03_video/assets/elephant/faces \
      --out person_scan_result.csv --detail-json person_scan_detail.json

gallery 目录约定：
  <gallery>/target/韦布.jpg, 黄玲.jpg, 于城.jpg ...
  <gallery>/blacklist/王金.jpg ...        # 王金=老人（同一角色，合并成一个文件即可）
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
DET_MODEL = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
REC_MODEL = MODEL_DIR / "face_recognition_sface_2021dec.onnx"

DEFAULT_SIM_THRESHOLD = 0.363   # SFace 官方 LFW 余弦阈值
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
YUNET_SIZE = 640


def require_models() -> None:
    missing = [str(p) for p in (DET_MODEL, REC_MODEL) if not p.exists() or p.stat().st_size < 1024]
    if missing:
        raise FileNotFoundError(
            "缺少人脸模型文件（或文件不完整，Git LFS 指针文件只有 ~130 字节）：\n  "
            + "\n  ".join(missing)
            + "\n请按 SKILL.md 的 media.githubusercontent.com / huggingface 地址重新下载到 models/ 目录。"
        )


def _nms(boxes: np.ndarray, scores: np.ndarray, thr: float, top_k: int = 5000) -> list[int]:
    if len(boxes) == 0:
        return []
    x1, y1, w, h = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = w * h
    order = scores.argsort()[::-1][:top_k]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x1[i] + w[i], x1[order[1:]] + w[order[1:]])
        yy2 = np.minimum(y1[i] + h[i], y1[order[1:]] + h[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= thr]
    return keep


class FaceEngine:
    """YuNet(ORT) 检测 + SFace(OpenCV) 特征。人脸行格式与 OpenCV 一致：x,y,w,h,10 个关键点,score。"""

    def __init__(self, score_thr: float = 0.7, nms_thr: float = 0.3):
        require_models()
        self.sess = ort.InferenceSession(str(DET_MODEL), providers=["CPUExecutionProvider"])
        self.rec = cv2.FaceRecognizerSF.create(str(REC_MODEL), "")
        self.score_thr = score_thr
        self.nms_thr = nms_thr

    def detect(self, img: np.ndarray, min_face_px: int = 40) -> list[np.ndarray]:
        h, w = img.shape[:2]
        s = YUNET_SIZE / max(h, w)
        nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
        canvas = np.full((YUNET_SIZE, YUNET_SIZE, 3), 114, dtype=np.uint8)
        canvas[:nh, :nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        blob = cv2.dnn.blobFromImage(canvas, 1.0, (YUNET_SIZE, YUNET_SIZE),
                                     swapRB=True, crop=False)
        outs = self.sess.run(["cls_8", "obj_8", "bbox_8", "kps_8",
                              "cls_16", "obj_16", "bbox_16", "kps_16",
                              "cls_32", "obj_32", "bbox_32", "kps_32"], {"input": blob})
        o = {n: v for n, v in zip(["cls_8", "obj_8", "bbox_8", "kps_8",
                                   "cls_16", "obj_16", "bbox_16", "kps_16",
                                   "cls_32", "obj_32", "bbox_32", "kps_32"], outs)}
        boxes, scores, kpss = [], [], []
        for stride in (8, 16, 32):
            cls = o[f"cls_{stride}"][0]
            obj = o[f"obj_{stride}"][0]
            bbox = o[f"bbox_{stride}"][0]
            kps = o[f"kps_{stride}"][0]
            cols = YUNET_SIZE // stride
            sc = np.sqrt(np.clip(cls[:, 0], 0, 1) * np.clip(obj[:, 0], 0, 1))
            idx = np.where(sc >= self.score_thr)[0]
            for i in idx:
                r, c = int(i) // cols, int(i) % cols
                cx = (c + bbox[i, 0]) * stride
                cy = (r + bbox[i, 1]) * stride
                bw = math.exp(float(bbox[i, 2])) * stride
                bh = math.exp(float(bbox[i, 3])) * stride
                boxes.append([cx - bw / 2, cy - bh / 2, bw, bh])
                scores.append(float(sc[i]))
                kpss.append([((c + kps[i, 2 * k]) * stride, (r + kps[i, 2 * k + 1]) * stride)
                             for k in range(5)])
        if not boxes:
            return []
        boxes_a = np.asarray(boxes, np.float32) / s
        keep = _nms(boxes_a, np.asarray(scores, np.float32), self.nms_thr)
        out = []
        for i in keep:
            x, y, bw, bh = boxes_a[i]
            if min(bw, bh) < min_face_px:
                continue
            row = np.array([x, y, bw, bh] + [v / s for p in kpss[i] for v in p] + [scores[i]],
                           dtype=np.float32)
            out.append(row)
        return out

    def embed(self, img: np.ndarray, face_row: np.ndarray) -> np.ndarray:
        aligned = self.rec.alignCrop(img, face_row)
        v = np.asarray(self.rec.feature(aligned), dtype=np.float32).reshape(-1)
        n = np.linalg.norm(v)
        return v / n if n > 0 else v


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


@dataclass
class Gallery:
    target: dict[str, np.ndarray] = field(default_factory=dict)
    blacklist: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.target and not self.blacklist


def load_gallery(gallery_dir: Path, engine: FaceEngine) -> Gallery:
    """优先读 index.json 里缓存的 embedding（建库时从原始帧提取，避免二次检测失败）；
    没有 index.json 时才退化为对头像图现场检测。"""
    g = Gallery()
    index = gallery_dir / "index.json"
    if index.exists():
        data = json.loads(index.read_text(encoding="utf-8"))
        for role, bucket in (("target", g.target), ("blacklist", g.blacklist)):
            for name, item in (data.get(role) or {}).items():
                vec = item.get("embedding")
                if vec:
                    v = np.asarray(vec, dtype=np.float32)
                    n = float(np.linalg.norm(v))
                    bucket[name] = v / n if n > 0 else v
        return g

    for role, bucket in (("target", g.target), ("blacklist", g.blacklist)):
        d = gallery_dir / role
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.suffix.lower() not in IMG_EXT:
                continue
            img = cv2.imread(str(p))
            if img is None:
                print(f"[warn] 读不了参考图：{p}")
                continue
            faces = engine.detect(img, min_face_px=24)
            if not faces:
                print(f"[warn] 参考图里没检出人脸，已跳过：{p.name}（建议用 --build-gallery 重建）")
                continue
            faces.sort(key=lambda f: f[2] * f[3], reverse=True)
            bucket[p.stem] = engine.embed(img, faces[0])
    return g


def extract_frames(video: Path, start: float, end: float, fps: float, outdir: Path,
                   width: int = 960) -> list[tuple[int, float]]:
    """ffmpeg 顺序抽帧（比 OpenCV 反复 seek 稳定），返回 [(帧序号, 时间戳)]。"""
    outdir.mkdir(parents=True, exist_ok=True)
    pattern = outdir / "f_%06d.jpg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                    "-i", str(video), "-vf", f"fps={fps},scale={width}:-2", "-q:v", "3",
                    str(pattern)], check=True)
    n = len(list(outdir.glob("f_*.jpg")))
    return [(i, start + (i - 1) / fps) for i in range(1, n + 1)]


def scan(video: Path, start: float, end: float, gallery: Gallery,
         window: float = 4.0, fps: float = 1.0, min_score: float = 0.7,
         min_face_px: int = 48, sim_threshold: float = DEFAULT_SIM_THRESHOLD,
         frame_width: int = 960) -> tuple[list[dict], list[dict]]:
    tmp = Path(tempfile.mkdtemp(prefix="pscan_"))
    frames = extract_frames(video, start, end, fps, tmp, frame_width)
    if not frames:
        return [], []

    engine = FaceEngine(min_score, 0.3)
    n_win = max(1, math.ceil((end - start) / window))
    agg = [{"faces": 0, "target": {}, "black": {}, "best": 0.0} for _ in range(n_win)]

    for idx, ts in frames:
        img = cv2.imread(str(tmp / f"f_{idx:06d}.jpg"))
        if img is None:
            continue
        faces = engine.detect(img, min_face_px)
        if not faces:
            continue
        wi = min(n_win - 1, int((ts - start) // window))
        a = agg[wi]
        a["faces"] = max(a["faces"], len(faces))
        for f in faces:
            emb = engine.embed(img, f)
            for name, ref in gallery.target.items():
                s = cosine(emb, ref)
                a["best"] = max(a["best"], s)
                if s >= sim_threshold and s > a["target"].get(name, 0.0):
                    a["target"][name] = round(s, 4)
            for name, ref in gallery.blacklist.items():
                s = cosine(emb, ref)
                a["best"] = max(a["best"], s)
                if s >= sim_threshold and s > a["black"].get(name, 0.0):
                    a["black"][name] = round(s, 4)

    rows, detail = [], []
    for i, a in enumerate(agg):
        s0, s1 = start + i * window, min(end, start + (i + 1) * window)
        rows.append({
            "start": round(s0, 2),
            "end": round(s1, 2),
            "target_person_hit": int(bool(a["target"])),
            "blacklist_person_hit": int(bool(a["black"])),
            "face_count": a["faces"],
            "confidence": round(a["best"], 3),
        })
        detail.append({
            "start": round(s0, 2), "end": round(s1, 2),
            "targets": a["target"], "blacklist": a["black"],
            "face_count": a["faces"], "max_similarity": round(a["best"], 3),
            "verdict": "blacklist" if a["black"] else ("target" if a["target"] else "nobody"),
        })
    return rows, detail


def build_gallery(spec_path: Path, video_dir: Path, gallery_dir: Path) -> int:
    """从已知镜头裁人脸建参考库。spec: [{"name":"于城","role":"target","src":"导剪002.mp4","times":[1634,1640,1646]}]

    关键点：embedding 直接从**原始帧的检测结果**提取并写入 index.json，
    而不是对裁剪后的小图重新检测 —— YuNet 在"极端侧脸 + 大特写裁剪"上会失效（已实测），
    但在正常画幅里能稳定检出。
    """
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    engine = FaceEngine(0.5, 0.3)
    index = {"target": {}, "blacklist": {}}
    made = 0
    for item in spec:
        video = (video_dir / item["src"]).resolve()
        times = item.get("times") or [item["time"]]
        best = None
        for t in times:
            tmp = Path(tempfile.mkdtemp(prefix="pref_"))
            img_path = tmp / "one.jpg"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{float(t):.3f}", "-i", str(video),
                            "-frames:v", "1", str(img_path)], check=True)
            img = cv2.imread(str(img_path))
            if img is None:
                continue
            faces = engine.detect(img, min_face_px=40)
            if not faces:
                continue
            faces.sort(key=lambda f: f[2] * f[3], reverse=True)
            f = faces[0]
            if best is None or f[2] * f[3] > best[0]:
                best = (f[2] * f[3], t, img.copy(), f.copy())
        if best is None:
            print(f"[fail] {item['name']}: {item['src']} {times} 内没有检到人脸，请换时间点")
            continue
        _, t, img, f = best
        x, y, w, h = [int(v) for v in f[:4]]
        pad = int(0.35 * max(w, h))
        crop = img[max(0, y - pad):min(img.shape[0], y + h + pad),
                   max(0, x - pad):min(img.shape[1], x + w + pad)]
        out = gallery_dir / item["role"] / f"{item['name']}.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out), crop)
        emb = engine.embed(img, f)
        index[item["role"]][item["name"]] = {
            "file": f"{item['role']}/{item['name']}.jpg",
            "embedding": [round(float(v), 6) for v in emb],
            "seed": {"src": item["src"], "time": t, "box": [int(x), int(y), int(w), int(h)],
                     "det_score": round(float(f[-1]), 3)},
            "note": item.get("note", ""),
        }
        print(f"[ref] {item['role']}/{item['name']}.jpg <- {item['src']}@{t:.2f}s "
              f"face={int(w)}x{int(h)} det={float(f[-1]):.2f}")
        made += 1
    if made:
        (gallery_dir / "index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description="画面人物检索（YuNet+SFace，纯CPU）")
    ap.add_argument("--video")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=60.0)
    ap.add_argument("--gallery", default=r"D:\00_skiill_ku\03_video\assets\elephant\faces")
    ap.add_argument("--window", type=float, default=4.0)
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--min-score", type=float, default=0.7)
    ap.add_argument("--min-face", type=int, default=48)
    ap.add_argument("--sim-threshold", type=float, default=DEFAULT_SIM_THRESHOLD)
    ap.add_argument("--frame-width", type=int, default=960)
    ap.add_argument("--out", default="person_scan_result.csv")
    ap.add_argument("--detail-json", default="")
    ap.add_argument("--build-gallery", action="store_true")
    ap.add_argument("--spec", default="")
    ap.add_argument("--video-dir", default=r"D:\00_skiill_ku\03_video\assets\elephant\raw")
    a = ap.parse_args()

    if a.build_gallery:
        if not a.spec:
            ap.error("--build-gallery 需要 --spec faces_seed.json")
        n = build_gallery(Path(a.spec), Path(a.video_dir), Path(a.gallery))
        print(f"gallery built: {n} refs -> {a.gallery}")
        return 0 if n else 2

    if not a.video:
        ap.error("扫描模式需要 --video")

    gal = load_gallery(Path(a.gallery), FaceEngine(0.7, 0.3))
    if gal.empty:
        print(f"[warn] 参考库为空（{a.gallery}/target|blacklist 下没有可用头像），全部结果将记为未命中。")
    rows, detail = scan(Path(a.video), a.start, a.end, gal, a.window, a.fps,
                        a.min_score, a.min_face, a.sim_threshold, a.frame_width)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=["start", "end", "target_person_hit",
                                          "blacklist_person_hit", "face_count", "confidence"])
        w.writeheader()
        w.writerows(rows)
    if a.detail_json:
        Path(a.detail_json).write_text(json.dumps(
            {"video": str(a.video), "gallery": str(a.gallery), "window": a.window,
             "sim_threshold": a.sim_threshold, "windows": detail}, ensure_ascii=False, indent=1),
            encoding="utf-8")

    nt = sum(r["target_person_hit"] for r in rows)
    nb = sum(r["blacklist_person_hit"] for r in rows)
    print(f"windows={len(rows)} target_hit={nt} blacklist_hit={nb} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
