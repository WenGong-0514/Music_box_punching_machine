"""生成测试音频: 用 30 音音表合成一段"小星星"风格旋律 WAV + MP3。
旋律尽量落在音表内, 并在结尾加一段超出音域的音(测试八度折叠)。
"""
from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.notetable import NoteTable  # noqa: E402

SR = 22050
OUT = Path(__file__).resolve().parent / "media"
OUT.mkdir(parents=True, exist_ok=True)


def pluck(freq: float, dur: float, amp: float = 0.5, sr: int = SR) -> np.ndarray:
    n = int(dur * sr)
    t = np.arange(n) / sr
    v = np.zeros(n)
    # 基波 + 泛音, 指数衰减(近似八音盒音)
    for k, a, tau in [(1, 1.0, 0.16), (2, 0.5, 0.09), (3, 0.25, 0.06), (4, 0.12, 0.05)]:
        v += a * np.sin(2 * np.pi * k * freq * t) * np.exp(-t / tau)
    return (v * amp / 1.6).astype(np.float32)


def note_freq(tab: NoteTable, name: str) -> float:
    for c in tab.columns:
        if c.label == name:
            return c.freq
    raise KeyError(name)


def build() -> Path:
    import sys as _sys
    dump_gt = "--gt" in _sys.argv
    gt_events = []
    from server.notetable import DEFAULT_BASE_OCTAVE, DEFAULT_COLUMNS
    tab = NoteTable(DEFAULT_COLUMNS, DEFAULT_BASE_OCTAVE)
    # 小星星 主旋律 (音表内: C1 D1 E1 F1 G1 A1 B1 即科学音高 C4..B4)
    # 每行: (音名或 None=休止, 拍数)
    melody = [
        ("C1", 1), ("C1", 1), ("G1", 1), ("G1", 1), ("A1", 1), ("A1", 1), ("G1", 2),
        ("F1", 1), ("F1", 1), ("E1", 1), ("E1", 1), ("D1", 1), ("D1", 1), ("C1", 2),
        ("G1", 1), ("G1", 1), ("F1", 1), ("F1", 1), ("E1", 1), ("E1", 1), ("D1", 2),
        ("G1", 1), ("G1", 1), ("F1", 1), ("F1", 1), ("E1", 1), ("E1", 1), ("D1", 2),
        ("C1", 1), ("C1", 1), ("G1", 1), ("G1", 1), ("A1", 1), ("A1", 1), ("G1", 2),
        ("F1", 1), ("F1", 1), ("E1", 1), ("E1", 1), ("D1", 1), ("D1", 1), ("C1", 2),
    ]
    # 低音伴奏(可落表内低音 C D G A B; 其余音跳过)
    bass_map = {"C1": "C", "G1": "G", "A1": "A", "D1": "D", "E1": None, "F1": None}
    bpm = 120.0
    beat_s = 60.0 / bpm
    total_s = sum(d for _, d in melody) * beat_s + 3.0
    x = np.zeros(int(total_s * SR), dtype=np.float32)
    tcur = 0.0
    for name, beats in melody:
        dur = beats * beat_s * 0.9
        if name:
            f = note_freq(tab, name)
            seg = pluck(f, dur, amp=0.42)
            s = int(tcur * SR)
            x[s:s + len(seg)] += seg[:max(0, len(x) - s)]
            gt_events.append({"t": round(tcur, 3), "midi": round(69 + 12 * math.log(f / 440, 2)), "src": "melody"})
            # 低音
            if name in bass_map and bass_map[name]:
                fb = note_freq(tab, bass_map[name])
                segb = pluck(fb, dur, amp=0.3)
                x[s:s + len(segb)] += segb[:max(0, len(x) - s)]
                gt_events.append({"t": round(tcur, 3), "midi": round(69 + 12 * math.log(fb / 440, 2)), "src": "bass"})
        tcur += beats * beat_s
    # 结尾: 一句高音旋律, 故意超出音表范围(>E6=88, 用 C7 D7 E7)测试八度折叠
    hi = [(96, 1), (98, 1), (100, 1), (96, 2)]  # (midi, 拍)
    for midi, beats in hi:
        dur = beats * beat_s * 0.9
        f = 440.0 * 2 ** ((midi - 69) / 12)
        seg = pluck(f, dur, amp=0.4)
        s = int(tcur * SR)
        x[s:s + len(seg)] += seg[:max(0, len(x) - s)]
        gt_events.append({"t": round(tcur, 3), "midi": midi, "src": "high_oct_test"})
        tcur += beats * beat_s
    if dump_gt:
        import json
        gt = {"notes": gt_events,
              "bpm": bpm, "beats_per_sec": bpm / 60.0}
        p = OUT / "gt_twinkle.json"
        p.write_text(json.dumps(gt, ensure_ascii=False, indent=1), encoding="utf-8")
        print("gt:", p, len(gt_events))
    # 归一化
    x = x / max(1e-9, np.max(np.abs(x))) * 0.9
    wav = OUT / "twinkle_30note.wav"
    sf.write(str(wav), x.astype(np.float32), SR)
    mp3 = OUT / "twinkle_30note.mp3"
    ff = subprocess.run(["ffmpeg", "-y", "-i", str(wav), "-b:a", "192k", str(mp3)],
                        capture_output=True)
    if ff.returncode != 0:
        print("mp3 编码跳过:", ff.stderr.decode(errors="ignore")[-150:])
    else:
        print("mp3:", mp3, mp3.stat().st_size, "bytes")
    return wav


if __name__ == "__main__":
    p = build()
    print("wav:", p)
