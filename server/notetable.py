"""30音音表模型: 打孔列(0..29) <-> 音高(MIDI/频率)。

标准 30 音纸带八音盒音阶 (两个独立来源 + 用户输入一致):
    C D G A B C1 D1 E1 F1 #F1 G1 #G1 A1 #A1 B1 C2 #C2 D2 #D2 E2 F2 #F2 G2
    #G2 A2 #A2 B2 C3 D3 E3
说明: 低音区(C,D,G,A,B)为自然音; 半音从 E1 起才齐全; 顶部 C3..E3 为自然音。
标签约定: 无数字 = base_octave 八度; 数字 n = base_octave+n 八度。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

A4_FREQ = 440.0
MIDI_A4 = 69

# 内置标准音表(与 data/note_table_30note.json 一致, 供无配置文件时兜底)
DEFAULT_COLUMNS = [
    "C", "D", "G", "A", "B",
    "C1", "D1", "E1", "F1", "F#1", "G1", "G#1", "A1", "A#1", "B1",
    "C2", "C#2", "D2", "D#2", "E2", "F2", "F#2", "G2", "G#2", "A2", "A#2", "B2",
    "C3", "D3", "E3",
]
DEFAULT_BASE_OCTAVE = 3

_NATURAL = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_LETTERS = "ABCDEFG"

midi_to_freq = lambda m: A4_FREQ * (2.0 ** ((m - MIDI_A4) / 12.0))
freq_to_midi = lambda f: 69.0 + 12.0 * (math_log2(f / A4_FREQ) if f > 0 else -999)


def _log2(x):
    import math
    return math.log(x) / math.log(2.0)


def parse_label_to_midi(token: str, base_octave: int = DEFAULT_BASE_OCTAVE) -> int | None:
    """把 'C'/'#F1'/'F#1'/'C3' 之类标签解析成 MIDI 整数; 无法解析返回 None。"""
    s = token.strip().upper().replace("♯", "#").replace("＃", "#").replace("♭", "b")
    has_sharp = "#" in s
    s = s.replace("#", "")
    m = re.fullmatch(r"([A-G])(\d?)", s)
    if not m:
        return None
    letter, oct_digit = m.group(1), m.group(2)
    if letter not in _NATURAL:
        return None
    octave = base_octave + (int(oct_digit) if oct_digit else 0)
    return 12 * (octave + 1) + _NATURAL[letter] + (1 if has_sharp else 0)


@dataclass(frozen=True)
class NoteColumn:
    """一列打孔位对应的音。"""
    index: int          # 0..29, 0=最低音
    label: str          # 原始标签
    name: str           # 规范名(含#, 如 C#2)
    midi: int
    freq: float

    def to_dict(self) -> dict:
        return {"index": self.index, "label": self.label, "name": self.name,
                "midi": self.midi, "freq": round(self.freq, 3)}


class NoteTable:
    """整张 30 列音表。"""

    def __init__(self, columns: list[str], base_octave: int = DEFAULT_BASE_OCTAVE,
                 table_id: str = "30note_standard", name: str = "", source: str = ""):
        if len(columns) != 30:
            raise ValueError(f"音表必须恰有 30 列, 实际 {len(columns)}")
        cols: list[NoteColumn] = []
        for i, lab in enumerate(columns):
            midi = parse_label_to_midi(lab, base_octave)
            if midi is None:
                raise ValueError(f"无法解析音名: {lab!r} (第{i + 1}列)")
            cols.append(NoteColumn(index=i, label=lab, name=_canon(lab),
                                   midi=midi, freq=midi_to_freq(midi)))
        # 必须严格递增, 否则物理上无意义
        for a, b in zip(cols, cols[1:]):
            if b.midi <= a.midi:
                raise ValueError(f"音表必须按音高严格递增, 第{a.index + 1}列 {a.label} 与第{b.index + 1}列 {b.label} 冲突")
        self.columns = cols
        self.base_octave = base_octave
        self.table_id = table_id
        self.name = name or f"30音表(base octave {base_octave})"
        self.source = source
        self.min_midi = cols[0].midi
        self.max_midi = cols[-1].midi

    # ---- 查询 ----
    def col(self, index: int) -> NoteColumn:
        return self.columns[index]

    def find_nearest(self, midi: float) -> tuple[NoteColumn, float]:
        """返回 (最近列, 音分误差)。midi 允许小数。"""
        best, best_err = self.columns[0], 1e18
        for c in self.columns:
            err = abs(midi - c.midi) * 100.0
            if err < best_err:
                best, best_err = c, err
        return best, best_err

    def fold_into_range(self, midi: float) -> tuple[NoteColumn, float, int] | None:
        """把任意音高折叠进音表范围(±几个八度), 返回 (列, 音分误差, 折叠八度数); None=无法折叠。"""
        span = self.max_midi - self.min_midi
        lo = self.min_midi
        best = None
        for oct_shift in range(-6, 7):
            cand = midi + 12 * oct_shift
            if self.min_midi - 0.5 <= cand <= self.max_midi + 0.5:
                col, err = self.find_nearest(cand)
                cand2 = col.midi + 12 * oct_shift
                err2 = abs(midi - cand2) * 100.0
                if best is None or err2 < best[1]:
                    best = (col, err2, -oct_shift)
        return best

    # ---- 序列化 ----
    def to_dict(self) -> dict:
        return {
            "id": self.table_id, "name": self.name, "source": self.source,
            "base_octave": self.base_octave,
            "columns": [c.label for c in self.columns],
            "notes": [c.to_dict() for c in self.columns],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NoteTable":
        return cls(columns=d["columns"], base_octave=int(d.get("base_octave", DEFAULT_BASE_OCTAVE)),
                   table_id=d.get("id", "custom"), name=d.get("name", ""), source=d.get("source", ""))


def _canon(token: str) -> str:
    """规范化标签: F#1 / #F1 -> C# 风格统一为 X#n (与音乐常识一致)。"""
    s = token.strip().upper().replace("#", "#")
    if s.startswith("#") and len(s) >= 2:
        s = s[1] + "#" + s[2:]
    return s


def load_note_table(path: str | Path | None = None) -> NoteTable:
    """从 JSON 加载音表; 缺省用内置标准 30 音表。"""
    if path:
        p = Path(path)
        if p.exists():
            return NoteTable.from_dict(json.loads(p.read_text(encoding="utf-8")))
    return NoteTable(DEFAULT_COLUMNS, DEFAULT_BASE_OCTAVE,
                     table_id="30note_standard", name="标准30音纸带八音盒",
                     source="内置: C D G A B C1..E3 (Sohu DIY + MMDigest Sankyo 印证)")
