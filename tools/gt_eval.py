"""用已知真值合成音频(twinkle)对多个引擎做音符级评测。

用法: 先跑各引擎生成 events json, 再
  python tools/gt_eval.py <events1.json> <events2.json> ...
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
GT = ROOT / "tools" / "media" / "gt_twinkle.json"


def load_ev(p: Path) -> list:
    d = json.loads(p.read_text(encoding="utf-8"))
    ev = []
    for e in d.get("events", []):
        f = e.get("freq")
        if not f or f <= 0:
            continue
        ev.append((e["start_s"], 69 + 12 * math.log(f / 440.0, 2)))
    return ev


def stats(path: Path, gt, tol_s: float = 0.12, tol_st: float = 0.75):
    pred = load_ev(path)
    matched_gt = set()
    matched_pred = 0
    used_pred = set()
    for i, (t, m) in enumerate(gt):
        best = None
        for j, (pt, pm) in enumerate(pred):
            if j in used_pred:
                continue
            d_t = abs(pt - t)
            if d_t > tol_s:
                continue
            dm = abs(pm - m)
            score = d_t + min(dm, 24) * 0.3
            if best is None or score < best[0]:
                best = (score, j, dm)
        if best is not None and best[2] <= tol_st:
            matched_gt.add(i)
            used_pred.add(best[1])
            matched_pred += 1
    prec = matched_pred / max(1, len(pred))
    rec = len(matched_gt) / max(1, len(gt))
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return prec, rec, f1, len(pred)


def main() -> int:
    files = [Path(a) for a in sys.argv[1:]]
    if not files:
        print("用法: gt_eval.py events1.json events2.json ...")
        return 2
    gt = [(n["t"], float(n["midi"])) for n in json.loads(GT.read_text(encoding="utf-8"))["notes"]]
    print(f"GT 音符: {len(gt)} (容差 {0.12}s / ±{0.75}半音)")
    print(f"{'引擎':<28} {'音符':>5} {'精度':>7} {'召回':>7} {'F1':>6}")
    for f in files:
        prec, rec, f1, n = stats(f, gt)
        print(f"{f.stem:<28} {n:5d} {prec:7.1%} {rec:7.1%} {f1:6.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
