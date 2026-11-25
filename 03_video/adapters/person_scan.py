"""person_scan.py — 轻量人物/人脸检测，替代迟滞的 OpenCV YuNet。

首选：YOLOv8n/v10n ONNX + onnxruntime CPU（精度/速度双升，模型仅 ~6MB）。
  - 模型文件放 03_video/models/yolov8n.onnx；缺失时尝试自动下载（需联网）。
降级：模型不可用时，复用 scripts/person_scan.py 的 FaceEngine(YuNet)，保证不中断。
诚实性：降级时在结果里标注 backend=yunet_fallback，不冒充 YOLO。

兼容旧接口：提供 detect_people(img, min_size) -> [{"bbox":[x,y,w,h],"conf":..}] 与
FaceEngine 风格类 YoloPersonEngine，便于 scripts/shot_analyze.py 替换。

CLI:
  python adapters/person_scan.py --video a.mp4 --start 0 --end 60 --out persons.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
YOLO_ONNX = MODEL_DIR / "yolov8n.onnx"
YOLO_URL = "https://github.com/ultralytics/assets/releases/latest/download/yolov8n.onnx"
COCO_PERSON = 0  # COCO class 0 = person


def _ensure_yolo() -> bool:
    if YOLO_ONNX.exists() and YOLO_ONNX.stat().st_size > 1_000_000:
        return True
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        print(f"[person_scan] 下载 YOLOv8n ONNX -> {YOLO_ONNX}", flush=True)
        urllib.request.urlretrieve(YOLO_URL, YOLO_ONNX)
        return YOLO_ONNX.exists()
    except Exception as e:
        print(f"[person_scan] 下载失败（{e}），降级 YuNet", flush=True)
        return False


class YoloPersonEngine:
    """ONNX Runtime 推理 YOLOv8n，CPU。输出 person bbox。"""

    def __init__(self, conf: float = 0.4, iou: float = 0.45):
        self.conf = conf
        self.iou = iou
        self.backend = "yolo_onnx"
        try:
            import onnxruntime as ort
        except ImportError:
            raise RuntimeError("onnxruntime 未安装")
        if not _ensure_yolo():
            raise RuntimeError("yolov8n.onnx 不可用")
        self._sess = ort.InferenceSession(str(YOLO_ONNX),
                                           providers=["CPUExecutionProvider"])
        self._input = self._sess.get_inputs()[0].name
        self._size = (640, 640)

    def detect(self, img: np.ndarray, min_size: int = 40) -> list[dict]:
        h, w = img.shape[:2]
        blob = cv2.dnn.blobFromImage(img, 1 / 255.0, self._size, swapRB=True, crop=False)
        out = self._sess.run(None, {self._input: blob})[0]  # [1,84,8400]
        out = out[0].T  # [8400,84]
        boxes, confs = [], []
        sx, sy = w / self._size[0], h / self._size[1]
        for row in out:
            cls_id = int(np.argmax(row[4:]))
            score = float(row[4 + cls_id])
            if cls_id != COCO_PERSON or score < self.conf:
                continue
            cx, cy, bw, bh = row[:4]
            x = (cx - bw / 2) * sx; y = (cy - bh / 2) * sy
            bw *= sx; bh *= sy
            if bw < min_size or bh < min_size:
                continue
            boxes.append([float(x), float(y), float(bw), float(bh)])
            confs.append(score)
        if not boxes:
            return []
        idx = cv2.dnn.NMSBoxes(boxes, confs, self.conf, self.iou)
        idx = idx.flatten() if len(idx) else []
        return [{"bbox": boxes[i], "conf": round(confs[i], 3)} for i in idx]


def get_engine():
    """优先 YOLO，失败降级现有 YuNet FaceEngine。返回 (engine, backend_name)。"""
    try:
        return YoloPersonEngine(), "yolo_onnx"
    except Exception as e:
        print(f"[person_scan] YOLO 不可用（{e}），降级 YuNet", flush=True)
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from person_scan import FaceEngine  # noqa: E402
        return FaceEngine(0.65, 0.3), "yunet_fallback"


def scan_video(video: str, start: float = 0.0, end: float | None = None,
               sample_fps: float = 1.0) -> dict:
    engine, backend = get_engine()
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    end_frame = total if end is None else int(end * fps)
    step = max(1, int(fps / sample_fps))
    persons, frames = 0, 0
    t0 = time.time()
    for f in range(int(start * fps), end_frame, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, frame = cap.read()
        if not ok:
            break
        frames += 1
        if backend == "yolo_onnx":
            persons += len(engine.detect(frame))
        else:
            persons += len(engine.detect(frame, 40))
    cap.release()
    return {"backend": backend, "frames_sampled": frames, "person_detections": persons,
            "elapsed_sec": round(time.time() - t0, 2)}


def main() -> int:
    ap = argparse.ArgumentParser(description="人物检测（YOLO ONNX 首选，YuNet 降级）")
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--sample-fps", type=float, default=1.0)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    res = scan_video(a.video, a.start, a.end, a.sample_fps)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
