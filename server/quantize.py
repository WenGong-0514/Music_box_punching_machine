"""量化编曲: 识别出的音符事件 -> 纸带孔 (row=时间步, col=0..29)。

映射规则(可配置):
  - 音高在音表范围内 -> 就近列
  - 超出范围: fold=整体移八度折回(冲突感知) | skip=丢弃 | clamp=夹到最低/最高列
  - auto_transpose: 社区主流做法——整曲搜索最佳移调(默认±12半音), 让更多音
    "原位"落在八音盒音域内, 减少八度折叠造成的和声堆叠
  - min_confidence 过滤弱识别; min_gap_steps 处理同列过近(读孔机械限制)
  - octave_ghost_suppress 抑制深度模型的八度泛音"鬼影"
"""
from __future__ import annotations

import math

from .notetable import NoteTable
from .tape import Tape, step_seconds


def _freq_to_midi(freq: float) -> float:
    return 69.0 + 12.0 * (math.log(freq / 440.0) / math.log(2.0))


def _cents_between(f1: float, f2: float) -> float:
    return 1200.0 * (math.log(f2 / f1) / math.log(2.0))


def suppress_octave_ghosts(events: list[dict], step_s: float,
                           dur_ratio: float = 0.6, conf_ratio: float = 0.62) -> tuple[list[dict], int]:
    """抑制"八度泛音鬼影": 深度模型对强谐波音会把高八度泛音误报成弱音符。

    规则: 同一时间窗(≤1步)内, 若某音符与组内最强音符频率成 2^k 八度关系(±25音分),
    且时长远短于最强音(<dur_ratio×)、置信度明显更低(<conf_ratio×), 判为鬼影丢弃。
    真实设计的八度和弦(时长/强度相当)不受影响。
    """
    if not events:
        return events, 0
    out: list[dict] = []
    dropped = 0
    groups: dict[int, list[int]] = {}
    for i, ev in enumerate(events):
        groups.setdefault(int(round(ev["start_s"] / step_s)), []).append(i)
    for _row, idxs in groups.items():
        if len(idxs) < 2:
            out.extend(events[i] for i in idxs)
            continue
        best = max(idxs, key=lambda i: (events[i].get("confidence", 0), events[i]["dur_s"]))
        bf, bd, bc = events[best]["freq"], events[best]["dur_s"], events[best].get("confidence", 0)
        for i in idxs:
            ev = events[i]
            f, d, c = ev["freq"], ev["dur_s"], ev.get("confidence", 0)
            oct_cents = abs(abs(_cents_between(f, bf)) % 1200.0 - 0.0)
            near_octave = oct_cents <= 25.0 or oct_cents >= 1175.0
            if (i != best and near_octave and f != bf
                    and d < dur_ratio * bd and c < conf_ratio * bc):
                dropped += 1
                continue
            out.append(ev)
    return out, dropped


def _fold_candidates(table: NoteTable, midi: float) -> list[tuple[int, float, int]]:
    """返回把 midi 折进音表的所有可行 (列, 音分误差, 折叠半音数) 候选, 按误差升序。"""
    cands = []
    for oct_shift in range(-7, 8):
        m2 = midi + 12 * oct_shift
        if m2 < table.min_midi or m2 > table.max_midi:
            continue
        c, err = table.find_nearest(m2)
        cands.append((c.index, err, -12 * oct_shift))
    cands.sort(key=lambda x: x[1])
    return cands


def _score_shift(events: list[dict], table: NoteTable, shift: int, step_s: float,
                 out_of_range: str, min_confidence: float, robust: bool = True) -> float:
    """给一个移调打分: 原位保留越多越好, 折叠/丢弃越少越好(近似, 不建孔)。

    robust=True 时, 距音表超过 ±1 个八度的"点缀性极高/极低音"(铃声、特效音等)
    权重≈0 —— 防止少数极高音把整曲移调拖低/拖高。
    """
    lo = table.min_midi - 12
    hi = table.max_midi + 12
    kept_in = kept_fold = kept_clamp = skipped = sparkle = 0.0
    for ev in events:
        if float(ev.get("confidence", 1.0)) < min_confidence:
            continue
        midi = _freq_to_midi(float(ev.get("freq", 0))) + shift
        if not (lo <= midi <= hi):
            if robust:
                sparkle += 0.02
                continue
            # 非鲁棒: 越界音也参与(旧行为)
        if table.min_midi - 0.5 <= midi <= table.max_midi + 0.5:
            kept_in += 1
        elif out_of_range == "fold":
            if _fold_candidates(table, midi):
                kept_fold += 1
            else:
                skipped += 1
        elif out_of_range == "clamp":
            kept_clamp += 1
        else:
            skipped += 1
    return kept_in + kept_fold * 0.35 + kept_clamp * 0.2 - skipped * 1.2 + sparkle


def quantize_to_tape(events: list[dict], table: NoteTable, *,
                     bpm: float = 120.0, steps_per_beat: int = 8,
                     min_confidence: float = 0.0,
                     out_of_range: str = "fold",
                     min_gap_steps: int = 0,
                     octave_ghost_suppress: bool = True,
                     transpose_semitones: int = 0,
                     auto_transpose: int = 0,
                     shift_robust: bool = True,
                     max_midi: float = 127.0,
                     min_midi: float = 0.0,
                     ) -> tuple[Tape, dict]:
    """返回 (Tape, stats)。events 见 engines 约定。

    transpose_semitones: 固定移调半音数(正=升高)。
    auto_transpose: >0 时在 ±auto_transpose 半音内自动搜索最优移调(覆盖固定值)。
    shift_robust: True 时极高/极低"点缀音"(铃音等)不主导移调选择。
    max_midi / min_midi: 音域过滤(单位: 移调前的原始MIDI); 超出直接丢弃,
        例如 max_midi=88 可把音表最高音以上的铃音全部去掉再量化。
    """
    step_s = step_seconds(bpm, steps_per_beat)
    if octave_ghost_suppress:
        events, ghost = suppress_octave_ghosts(events, step_s)
    else:
        ghost = 0
    holes: list[dict] = []
    seen: set[tuple[int, int]] = set()
    last_row_of_col: dict[int, int] = {}

    shift = int(transpose_semitones)
    if auto_transpose and auto_transpose > 0:
        best_s, best_score = 0, -1e18
        for s in range(-auto_transpose, auto_transpose + 1):
            sc = _score_shift(events, table, s, step_s, out_of_range,
                              min_confidence, robust=shift_robust)
            if sc > best_score:
                best_s, best_score = s, sc
        shift = best_s

    stats = {
        "total_events": len(events) + ghost,
        "ghost_dropped": ghost,
        "transpose_used": shift,
        "shift_robust": bool(shift_robust),
        "extreme_high": 0,     # 移调后仍高出音表≥1个八度的点缀音(铃音感)
        "extreme_low": 0,
        "register_dropped": 0,  # max/min_midi 音域过滤掉的音符
        "kept": 0,
        "dropped_low_conf": 0,
        "out_of_range_skipped": 0,
        "clamped": 0,
        "folded": 0,
        "duplicates": 0,
        "too_close": 0,
        "warnings": [],
    }

    for ev in events:
        conf = float(ev.get("confidence", 1.0))
        if conf < min_confidence:
            stats["dropped_low_conf"] += 1
            continue
        freq = float(ev.get("freq", 0.0))
        if freq <= 0:
            continue
        orig_midi = _freq_to_midi(freq)
        if orig_midi > max_midi or orig_midi < min_midi:
            stats["register_dropped"] += 1
            if stats["register_dropped"] <= 3:
                stats["warnings"].append({
                    "freq": round(freq, 1), "t_s": round(ev["start_s"], 1),
                    "reason": f"音域过滤(MIDI {min_midi:.0f}~{max_midi:.0f}之外)丢弃"})
            continue
        midi = orig_midi + shift
        # 统计"点缀性极高/极低音"(移调后仍超出音表≥1个八度)
        if midi > table.max_midi + 12:
            stats["extreme_high"] += 1
            if stats["extreme_high"] <= 3:
                stats["warnings"].append({
                    "freq": round(freq, 1), "t_s": round(ev["start_s"], 1),
                    "reason": "极高点缀音(折叠后仍会显得突兀)"})
        elif midi < table.min_midi - 12:
            stats["extreme_low"] += 1
        col: int | None = None
        how = ""
        row = int(round(ev["start_s"] / step_s))
        row_cols = set()
        for h in holes:
            if h["row"] == row:
                row_cols.add(h["col"])

        if table.min_midi - 0.5 <= midi <= table.max_midi + 0.5:
            c, _err = table.find_nearest(midi)
            col, how = c.index, "fit"
        elif out_of_range == "fold":
            cands = _fold_candidates(table, midi)
            if not cands:
                stats["out_of_range_skipped"] += 1
                continue
            # 冲突感知: 首选不与同拍其它音撞列的候选
            picked = next((c for c in cands if c[0] not in row_cols), cands[0])
            col, how = picked[0], "fold"
            stats["folded"] += 1
        elif out_of_range == "clamp":
            c = table.columns[0] if midi < table.min_midi else table.columns[-1]
            col, how = c.index, "clamp"
            stats["clamped"] += 1
        else:  # skip
            stats["out_of_range_skipped"] += 1
            if len(stats["warnings"]) < 20:
                stats["warnings"].append({"freq": round(freq, 1),
                                          "midi": round(midi - shift, 1),
                                          "reason": "超出30音范围(策略:跳过)"})
            continue

        key = (row, col)
        if key in seen:
            stats["duplicates"] += 1
            continue
        if min_gap_steps > 0 and col in last_row_of_col:
            if row - last_row_of_col[col] < min_gap_steps:
                stats["too_close"] += 1
                if len(stats["warnings"]) < 20:
                    stats["warnings"].append({"col": col, "row": row,
                                              "reason": f"同列间隔<{min_gap_steps}格(读孔限制)"})
                continue
        seen.add(key)
        last_row_of_col[col] = row
        holes.append({"row": row, "col": col})
        stats["kept"] += 1

    tape = Tape(holes=holes, bpm=bpm, steps_per_beat=steps_per_beat,
                table_id=table.table_id)
    tape.dedupe()
    stats["final_holes"] = tape.hole_count()
    return tape, stats
