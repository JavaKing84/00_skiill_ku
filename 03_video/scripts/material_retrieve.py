#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""material_retrieve.py — 多模态素材条件检索（复用前置分析结果，不解码视频、不建向量库）。

把三份已有分析结果按时间区间做交叠 join：
  person_scan  → 画面出现了谁（CSV + detail JSON）
  shot_analyze → 景别 / 运动 / 长短镜头（JSON）
  whisper      → 台词文本（JSON）

支持的条件（AND 组合）：
  --person 于城        画面必须出现该人物
  --exclude 王金       画面不得出现该人物
  --scale 中景         景别匹配（可多次传）
  --long-shot / --short-shot
  --dialogue 满洲里     台词包含关键词（多个用逗号，OR）
  --min-dur / --max-dur

输出 CSV：source,start,end,shot_scale,character_list,dialogue_text,confidence
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def _key(name: str) -> str:
    """把 导剪002.mp4 / whisper_002 / 002 统一成 '002'，用于跨文件对齐。"""
    stem = Path(name).stem
    nums = re.findall(r"\d+", stem)
    return nums[-1] if nums else stem


def _pair(arg: str, name: str) -> dict[str, Path]:
    """解析 "导剪001.mp4=path.csv,导剪002.mp4=path2.csv" """
    out = {}
    for item in filter(None, (x.strip() for x in arg.split(","))):
        if "=" not in item:
            raise SystemExit(f"{name} 需要 src=path 形式，收到：{item}")
        k, v = item.split("=", 1)
        out[Path(k).name] = Path(v)
    return out


def load_person(csv_map: dict[str, Path], detail_map: dict[str, Path]) -> dict[str, list[dict]]:
    data: dict[str, list[dict]] = {}
    for src, p in csv_map.items():
        rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
        det = []
        detail = detail_map.get(src) or detail_map.get(_key(src))
        if detail and detail.exists():
            det = json.loads(detail.read_text(encoding="utf-8")).get("windows", [])
        for i, r in enumerate(rows):
            item = {"start": float(r["start"]), "end": float(r["end"]),
                    "target": int(r["target_person_hit"]), "black": int(r["blacklist_person_hit"]),
                    "confidence": float(r["confidence"]), "names": [], "black_names": []}
            if i < len(det):
                item["names"] = list(det[i].get("targets", {}))
                item["black_names"] = list(det[i].get("blacklist", {}))
            data.setdefault(_key(src), []).append(item)
    return data


def load_shots(paths: list[Path]) -> list[dict]:
    shots = []
    for p in paths:
        shots += json.loads(p.read_text(encoding="utf-8"))
    return shots


def load_whisper(paths: list[Path]) -> dict[str, list[dict]]:
    data: dict[str, list[dict]] = {}
    for p in paths:
        raw = json.loads(p.read_text(encoding="utf-8"))
        segs = raw.get("segments", raw) if isinstance(raw, dict) else raw
        norm = []
        for s in segs:
            a = s.get("start", s.get("s"))
            b = s.get("end", s.get("e"))
            t = s.get("text", s.get("t", ""))
            if a is None or b is None:
                continue
            norm.append({"start": float(a), "end": float(b), "text": str(t).strip()})
        data.setdefault(_key(p.name), []).extend(norm)
    return data


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def retrieve(shots: list[dict], persons: dict[str, list[dict]], whisper: dict[str, list[dict]],
             source: str | None = None, need: list[str] | None = None,
             exclude: list[str] | None = None, scales: list[str] | None = None,
             long_shot: bool | None = None, dialogue: list[str] | None = None,
             min_dur: float | None = None, max_dur: float | None = None,
             avoid: list[dict] | None = None, require_empty: bool = False) -> list[dict]:
    """avoid：黑名单/禁支线避让窗口 [{key,start,end}]（已含缓冲），镜头与窗口有任何重叠即排除。
    require_empty：只要无人镜头（目标/黑名单都未命中），供 0 命中时的
    empty_shot_with_vo 自动降级使用。
    """
    need, exclude = need or [], exclude or []
    results = []
    for s in shots:
        src = Path(s.get("source", "")).name
        if source and src != Path(source).name and _key(src) != _key(source):
            continue
        if avoid:
            k = _key(src)
            if any(k == av["key"] and s["start_time"] < av["end"] and s["end_time"] > av["start"]
                   for av in avoid):
                continue
        dur = s.get("duration") or (s["end_time"] - s["start_time"])
        if min_dur is not None and dur < min_dur:
            continue
        if max_dur is not None and dur > max_dur:
            continue
        if scales and s.get("shot_scale") not in scales:
            continue
        if long_shot is True and not s.get("is_long_shot"):
            continue
        if long_shot is False and s.get("is_long_shot"):
            continue

        inside = [p for p in persons.get(_key(src), [])
                  if _overlap(p["start"], p["end"], s["start_time"], s["end_time"])
                  > 0.5 * min(p["end"] - p["start"], dur)]
        names, blacks, conf = [], [], 0.0
        for p in inside:
            names += p["names"] or (["target"] if p["target"] else [])
            blacks += p["black_names"] or (["blacklist"] if p["black"] else [])
            conf = max(conf, p["confidence"])
        names = list(dict.fromkeys(names))
        blacks = list(dict.fromkeys(blacks))
        chars = [n for n in names + blacks if n != "target" and n != "blacklist"]

        if need and not all(any(n == x or x in n for n in names) for x in need):
            continue
        if exclude and any(any(b == x or x in b for b in blacks) for x in exclude):
            continue
        if require_empty and (names or blacks):
            continue  # 降级模式：只收无人空镜

        texts = [w["text"] for w in whisper.get(_key(src), [])
                 if _overlap(w["start"], w["end"], s["start_time"], s["end_time"]) > 0.05]
        joined = " / ".join(dict.fromkeys(texts))
        if dialogue:
            low = joined.lower()
            if not any(k.lower() in low for k in dialogue):
                continue

        if require_empty:
            vtype = "empty_shot_with_vo"     # 0 命中降级：环境空镜 + 画外音
        elif chars or names:
            vtype = "person_shot"
        else:
            vtype = "empty_shot"
        results.append({"source": src, "start": s["start_time"], "end": s["end_time"],
                        "shot_scale": s.get("shot_scale", ""),
                        "character_list": "|".join(chars) if chars else ("target" if names else ""),
                        "dialogue_text": joined, "confidence": round(conf, 3),
                        "visual_type": vtype})
    results.sort(key=lambda r: (r["source"], r["start"]))
    return results


def _avoid_windows(path: Path, buffer: float) -> list[dict]:
    """读禁止支线/黑名单窗口 JSON，展开避让缓冲（±buffer 秒）。
    start<0 的窗口（区间未掌握，如枪支线 -1）保持禁用，不参与排除。"""
    out = []
    for fb in json.loads(path.read_text(encoding="utf-8")):
        s, e = float(fb.get("start", -1)), float(fb.get("end", -1))
        if s < 0 or e <= s:
            continue
        b = float(fb.get("buffer", buffer))
        out.append({"key": _key(fb.get("src", "")), "start": max(0.0, s - b), "end": e + b,
                    "name": fb.get("name", "")})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="多模态素材条件检索（基于前置分析结果）")
    ap.add_argument("--shots", nargs="+", required=True)
    ap.add_argument("--person-csv", default="")
    ap.add_argument("--person-detail", default="")
    ap.add_argument("--whisper", nargs="*", default=[])
    ap.add_argument("--source", default="")
    ap.add_argument("--person", default="")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--scale", default="")
    ap.add_argument("--long-shot", dest="long_shot", action="store_true", default=None)
    ap.add_argument("--short-shot", dest="long_shot", action="store_false")
    ap.add_argument("--dialogue", default="")
    ap.add_argument("--min-dur", type=float, default=None)
    ap.add_argument("--max-dur", type=float, default=None)
    ap.add_argument("--avoid-json", default="",
                    help="黑名单/禁支线窗口 JSON（配合 --avoid-buffer 物理避让）")
    ap.add_argument("--avoid-buffer", type=float, default=5.0,
                    help="敏感人物避让缓冲秒数（前后各 N 秒，默认 5）")
    ap.add_argument("--no-fallback", action="store_true",
                    help="关闭 0 命中自动降级（默认开启：降级为 empty_shot_with_vo）")
    ap.add_argument("--out", default="material_retrieve_result.csv")
    a = ap.parse_args()

    csv_map = _pair(a.person_csv, "--person-csv") if a.person_csv else {}
    detail_map = _pair(a.person_detail, "--person-detail") if a.person_detail else {}
    shots = load_shots([Path(p) for p in a.shots])
    persons = load_person(csv_map, detail_map)
    whisper = load_whisper([Path(p) for p in a.whisper])
    avoid = _avoid_windows(Path(a.avoid_json), a.avoid_buffer) if a.avoid_json else []
    if avoid:
        for w in avoid:
            print(f"avoid-window: {w['name']} {w['key']} {w['start']:.2f}-{w['end']:.2f}"
                  f"（含 ±{a.avoid_buffer}s 缓冲）")

    need = [x for x in a.person.split(",") if x]
    common = dict(source=a.source or None,
                  exclude=[x for x in a.exclude.split(",") if x],
                  scales=[x for x in a.scale.split(",") if x],
                  long_shot=a.long_shot,
                  dialogue=[x for x in a.dialogue.split(",") if x],
                  min_dur=a.min_dur, max_dur=a.max_dur, avoid=avoid)

    rows = retrieve(shots, persons, whisper, need=need, **common)

    # Fallback：指定人物命中 0 时自动降级为「环境空镜 + 画外音」，逐级放宽、打标不中断。
    # 梯子：①去人物条件（只要无人空镜）→ ②放宽长镜限制 → ③放宽台词过滤。
    # 任何一级拿到候选即停止；三级全空才返回 3（如实报告素材池枯竭）。
    fallback_used = ""
    if not rows and need and not a.no_fallback:
        stages = [
            ("去人物条件（无人空镜+画外音）", dict()),
            ("放宽长镜限制", dict(long_shot=None)),
            ("放宽台词过滤", dict(long_shot=None, dialogue=[])),
        ]
        for label, relax in stages:
            rows = retrieve(shots, persons, whisper, need=[], require_empty=True,
                            **{**common, **relax})
            if rows:
                fallback_used = label
                print(f"FALLBACK: 人物 {','.join(need)} 命中 0 条 → 自动降级 "
                      f"visual_type=empty_shot_with_vo（{label}），{len(rows)} 条候选，流水线继续")
                break
        if not rows:
            print("FALLBACK: 全部降级梯子走完仍无候选（人物/长镜/台词全放宽后素材池为空），如实报告不编造")

    out = Path(a.out)
    with out.open("w", newline="", encoding="utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=["source", "start", "end", "shot_scale",
                                          "character_list", "dialogue_text", "confidence",
                                          "visual_type"])
        w.writeheader()
        w.writerows(rows)
    print(f"matched={len(rows)}{' (fallback=empty_shot_with_vo: ' + fallback_used + ')' if fallback_used else ''} -> {out}")
    for r in rows[:20]:
        print(f"  {r['source']} {r['start']:8.2f}-{r['end']:8.2f} {r['shot_scale']} "
              f"[{r['character_list']}] {r['dialogue_text'][:30]} ({r['visual_type']})")
    if not rows:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
