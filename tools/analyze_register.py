"""音区/声部分布诊断: 看转录的主旋律中心与"突兀高音"是否合理(用于听感问题定位)。

用法: python tools/analyze_register.py <events.json> [<events2.json> ...]
指标:
  - 整体音符 MIDI 均值/中位数/P5..P95
  - 每秒最强音高的滚动"主旋律轨迹", 取其 中位数(主旋律中心) 与 离群高音数(>86 且孤立)
  - 与 C调版谱对照(谱面: 右手旋律中心≈G5(79), 左手≈A2-A3 附近)
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SCORE = ROOT / "tools" / "score_ref" / "xiaye_score.json"


def midis_of(path: Path) -> np.ndarray:
    d = json.loads(path.read_text(encoding="utf-8"))
    ms = []
    for e in d.get("events", []):
        f = e.get("freq")
        if not f or f <= 0:
            continue
        ms.append(69 + 12 * math.log(f / 440.0, 2))
    return np.array(ms)


def topvoice_stats(path: Path):
    """按 0.25s 分窗, 每窗取最高音 = 简易主旋律轨迹。"""
    d = json.loads(path.read_text(encoding="utf-8"))
    ev = []
    for e in d.get("events", []):
        f = e.get("freq")
        if not f or f <= 0:
            continue
        ev.append((e["start_s"], 69 + 12 * math.log(f / 440.0, 2)))
    if not ev:
        return None
    ev.sort()
    # 时间窗
    win = 0.25
    end = max(s for s, _ in ev) + win
    tops = []
    i = 0
    t0 = 0.0
    while t0 < end and i < len(ev):
        t1 = t0 + win
        best = None
        while i < len(ev) and ev[i][0] < t1:
            if best is None or ev[i][1] > best:
                best = ev[i][1]
            i += 1
        if best is not None:
            tops.append(best)
        t0 = t1
    return np.array(tops)


def report(label: str, p: Path, score_rh, score_lh):
    ms = midis_of(p)
    tops = topvoice_stats(p)
    print(f"\n=== {label} ({p.name}) ===")
    if len(ms) == 0:
        print("  无音符")
        return
    print(f"  音符数 {len(ms)}  整体 MIDI: 中位 {np.median(ms):.0f} 均值 {ms.mean():.0f} "
          f"P10={np.percentile(ms, 10):.0f} P90={np.percentile(ms, 90):.0f} "
          f"min={ms.min():.0f} max={ms.max():.0f}")
    if tops is not None:
        hi_iso = int((tops > 86).sum())
        print(f"  主旋律(每0.25s最高音)轨迹: 中位 {np.median(tops):.0f} "
              f"P10={np.percentile(tops, 10):.0f} P90={np.percentile(tops, 90):.0f}, "
              f"含 >86(突兀高)窗数 {hi_iso}")
    print(f"  谱面参照: 右手旋律 中位 {np.median(score_rh):.0f} "
          f"(范围 {score_rh.min():.0f}-{score_rh.max():.0f}), "
          f"左手 中位 {np.median(score_lh):.0f} (范围 {score_lh.min():.0f}-{score_lh.max():.0f})")


def main() -> int:
    files = [Path(a) for a in sys.argv[1:]]
    if not files:
        print("用法: analyze_register.py events.json ...")
        return 2
    sd = json.loads(SCORE.read_text(encoding="utf-8"))
    score_rh = np.array([n["midi"] for n in sd["notes"] if n["staff"] == 1])
    score_lh = np.array([n["midi"] for n in sd["notes"] if n["staff"] == 2])
    for f in files:
        report(f.stem, f, score_rh, score_lh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
