"""把引擎识别结果与 C调版标准钢琴谱(SVG解析)做近似对比, 输出可读报告。

用法:
  python tools/compare_to_score.py <events.json> [--title 引擎名] [--beats-per-measure 4]
events.json 为 eval_pipeline 输出的 {events:[{start_s,freq,...}]}。

局限(如实说明):
  * 音频为原曲演奏/混音, 谱面为"闫东炜-夏野与暗恋(C调版)"简化改编谱,
    两者在织体/音区/装饰音上本就有差异 -> 对比是"近似", 不是逐音 GT。
  * 通过搜索 BPM×相位 做粗略时间对齐; 和弦内多音一并统计。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def load_score(p: Path) -> dict:
    d = json.loads(p.read_text(encoding="utf-8"))
    notes = []
    for n in d["notes"]:
        onset_beat = (n["meas"] - 1) * 4.0 + n["onset_in_measure"]
        notes.append({"staff": n["staff"], "beat": onset_beat, "midi": n["midi"]})
    return {"notes": notes, "meta": d}


def events_to_midi_secs(events: list[dict]) -> list[dict]:
    out = []
    for e in events:
        f = e.get("freq") or e.get("pitch_hz")
        if not f or f <= 0:
            continue
        midi = 69 + 12 * math.log(f / 440.0) / math.log(2.0)
        out.append({"start": e["start_s"], "midi": midi,
                    "dur": e.get("dur_s", 0.1), "conf": e.get("confidence", 1.0)})
    return out


def align_tempo(score_notes, audio_secs, bpm_lo=40, bpm_hi=210):
    """网格搜索使谱面 onset 与音频 onset 对齐最好的 (bpm, t0)。"""
    best = (0, 0, -1e18)
    A = np.array(sorted(audio_secs))
    for bpm in np.arange(bpm_lo, bpm_hi, 0.5):
        per = 60.0 / bpm
        # 相位: 用第一个谱面 onset(0拍) 在时间上对齐音频onset分布
        # 直接把谱面节拍映射到 t = k*per, 与 A 比较容差窗
        for phase0 in np.arange(0, per, per / 8):
            tgt = (np.arange(0, 320) * per + phase0)  # 足够长
            d = np.abs(A[:, None] - tgt[None, :])
            hits = (d.min(axis=1) < 0.12).sum()
            if hits > best[2]:
                best = (bpm, phase0, hits)
    return best[0], best[1], best[2]


def pc_corr(a_midis, b_midis):
    """返回 (pa, pb, corr, best_shift_semitones): 在12个半音循环移位中取最大相关。"""
    ca = Counter(int(round(m)) % 12 for m in a_midis)
    cb = Counter(int(round(m)) % 12 for m in b_midis)
    total_a = sum(ca.values()) or 1
    total_b = sum(cb.values()) or 1
    pa = np.array([ca[i] / total_a for i in range(12)])
    pb0 = np.array([cb[i] / total_b for i in range(12)])
    best = (-1, -1e18, 0)
    for sh in range(12):
        pb = np.roll(pb0, sh)
        c = float(np.corrcoef(pa, pb)[0, 1])
        if c > best[1]:
            best = (c, sh)
    return pa, pb0, best[0], best[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("events_json")
    ap.add_argument("--title", default="")
    args = ap.parse_args()

    score = load_score(ROOT / "tools" / "score_ref" / "xiaye_score.json")
    s_notes = score["notes"]
    s_by_staff = {1: [n for n in s_notes if n["staff"] == 1],
                  2: [n for n in s_notes if n["staff"] == 2]}

    data = json.loads(Path(args.events_json).read_text(encoding="utf-8"))
    ev = events_to_midi_secs(data.get("events", []))
    audio_dur = data.get("duration_s", 0)
    if not ev:
        print("无音符事件")
        return 2

    print("=" * 62)
    print(f"《夏野与暗恋》识别 vs C调版标准钢琴谱   [{args.title or Path(args.events_json).stem}]")
    print("=" * 62)
    print(f"音频时长 {audio_dur:.1f}s · 谱面约 {int(max(n['beat'] for n in s_notes) / 4) + 1} 小节 · "
          f"谱面音符 {len(s_notes)} (右{len(s_by_staff[1])}/左{len(s_by_staff[2])})")

    # 1) 时长→节拍估计(粗)
    bpm, t0, hits = align_tempo(s_notes, [e["start"] for e in ev])
    print(f"\n[1] 估计速度 ≈ {bpm:.0f} BPM (对齐命中音频起点 {hits})")
    per = 60.0 / bpm
    print(f"    谱面总拍 ≈ {max(n['beat'] for n in s_notes) + 4:.0f} → 约 "
          f"{(max(n['beat'] for n in s_notes) + 4) * per:.0f}s (音频 {audio_dur:.0f}s)")

    # 2) 音级相关(整体调性相似度, 12半音移调取最优)
    pca, pcb0, corr, shift = pc_corr([e["midi"] for e in ev], [n["midi"] for n in s_notes])
    print(f"\n[2] 音级直方(12移调最优) r = {corr:.3f}, 谱面需上移 {shift} 半音"
          f"(录音比C调版谱高 {shift} 个半音)")
    pcb = np.roll(pcb0, shift)
    topa = np.argsort(pca)[::-1][:5]
    topb = np.argsort(pcb)[::-1][:5]
    print(f"    识别音级Top5: {[NAMES[i] for i in topa]}")
    print(f"    谱面移调后Top5: {[NAMES[i] for i in topb]}")

    # 3) 对齐窗口内的近似召回/精度(时间容差≈八分音符, 音高允许±1半音或±1八度错位)
    window = 0.28 * per   # ≈ 四分音符的 0.28(略宽于八分)
    for staff, label in [(1, "右手(旋律)", ), (2, "左手(伴奏)")]:
        sn = s_by_staff[staff]
        # 映射到时间, 并移调 shift
        s_t = []
        for n in sn:
            t = t0 + n["beat"] * per
            s_t.append((t, n["midi"] + shift))

        def ok_pitch(dm):
            return abs(dm) <= 1.5 or abs(abs(dm) - 12) <= 1.5 or abs(abs(dm) - 24) <= 1.5

        # 识别音符: 每时间窗内找最近谱面音并允许±1半音(或八度)
        ev_sorted = sorted(ev, key=lambda x: x["start"])
        matched_score = set()
        matched_ev = 0
        for e in ev_sorted:
            best_i, best_d = None, 1e9
            for i, (t, m) in enumerate(s_t):
                dd = abs(e["start"] - t) + min(abs(e["midi"] - m), 24) * 0.4
                if dd < best_d:
                    best_d, best_i = dd, i
            if best_i is not None:
                t, m = s_t[best_i]
                if abs(e["start"] - t) <= window and ok_pitch(e["midi"] - m):
                    matched_score.add(best_i)
                    matched_ev += 1
        recall = len(matched_score) / max(1, len(sn))
        # 精度粗略: 每谱面音只算一次命中
        prec = matched_ev / max(1, len(ev_sorted))
        # 每个命中谱面音窗口内识别命中数
        print(f"\n[3] {label}: 谱面 {len(sn)} 音, 命中 {len(matched_score)} "
              f"({recall * 100:.0f}% 召回); 识别音符 {matched_ev}/{len(ev)} "
              f"({prec * 100:.0f}%) 能在谱面±(半音/八度)内找到对应")
    return 0


if __name__ == "__main__":
    sys.exit(main())
