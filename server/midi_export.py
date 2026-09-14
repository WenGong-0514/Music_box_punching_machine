"""纸带 -> MIDI 导出(供钢琴软件/DAW 演奏或读谱)。

纸带模型: 每个 (row,col) 一个孔 = 一次拨弦; 时值靠孔间距表达, 孔本身不表音长。
因此导出时:
    start(row,col) = row * step_seconds
    pitch         = 该列(table.columns[col].midi)
    duration      = 到"同一列下一个孔"的距离(至少在 1 步、至多 4 步)
这样做比"固定短促音"更能让钢琴软件听出纸带本身的节奏间隔, 且和弦同刻开音。
"""
from __future__ import annotations

from pathlib import Path

from .tape import Tape


def tape_to_pretty_midi(tape: Tape, table=None):
    """返回 pretty_midi.PrettyMIDI。table 为 None 时 col->MIDI 用默认近似(48+col)。"""
    import pretty_midi  # type: ignore

    pm = pretty_midi.PrettyMIDI(initial_tempo=max(1.0, float(tape.bpm)))
    inst = pretty_midi.Instrument(program=0, is_drum=False, name="MusicBox Tape Piano")
    step = tape.step_seconds() if hasattr(tape, "step_seconds") else \
        (60.0 / (max(1.0, float(tape.bpm)) * max(1, int(tape.steps_per_beat))))
    # 同列按 row 排序的下一孔索引, 用于时长
    by_col: dict[int, list[int]] = {}
    for h in tape.holes:
        by_col.setdefault(int(h["col"]), []).append(int(h["row"]))
    for col in by_col:
        by_col[col].sort()

    note_max_midi = 127
    note_min_midi = 0

    def _pitch(h) -> int:
        col = int(h["col"])
        if table is not None and 0 <= col < len(table.columns):
            return int(table.columns[col].midi)
        return max(note_min_midi, min(note_max_midi, 48 + col))  # 无表时的近似

    rows_by_col = by_col
    for col, rows in rows_by_col.items():
        for i, row in enumerate(rows):
            nxt = rows[i + 1] if i + 1 < len(rows) else (row + 4)
            gap = max(1, int(nxt) - int(row))
            dur = min(4.0, max(1.0, float(gap))) * step
            start = float(row) * step
            pmn = pretty_midi.Note(velocity=92, pitch=_pitch({"col": col}),
                                   start=start, end=start + dur)
            inst.notes.append(pmn)
    pm.instruments.append(inst)
    return pm


def tape_to_midi_bytes(tape: Tape, table=None) -> bytes:
    """返回 .mid 文件字节。"""
    pm = tape_to_pretty_midi(tape, table)
    import io
    buf = io.BytesIO()
    pm.write(buf)
    return buf.getvalue()


def tape_to_midi_file(tape: Tape, out_path: str | Path, table=None) -> Path:
    p = Path(out_path)
    data = tape_to_midi_bytes(tape, table)
    p.write_bytes(data)
    return p
