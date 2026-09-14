"""MIDI 乐谱 -> 统一音符事件(选轨后可走既有③量化).

与"音频识别"的区别: MIDI 是"正确的谱面", 音符直接来自各音轨,
不用猜测。量化逻辑(30音表映射/自动移调/折叠/鬼影抑制/导出)全部复用。

乐器轨概念:
  - 标准 MIDI 每轨有一个 program(0..127, GM 音色), 0=Acoustic Grand Piano, 40=Violin 等;
  - 第 10 通道(鼓)无音高, 通常不适合 30 音表 → 默认标灰并提示;
  - 提取: 勾选一个或多个非鼓轨, 后端把选中轨道的音符合并成事件。
"""
from __future__ import annotations

from pathlib import Path

# GM 128 音色名(program 0..127); 见 General MIDI Level 1
GM_PROGRAMS = [
    "Acoustic Grand Piano", "Bright Acoustic Piano", "Electric Grand Piano", "Honky-tonk Piano",
    "Electric Piano 1", "Electric Piano 2", "Harpsichord", "Clavinet",
    "Celesta", "Glockenspiel", "Music Box", "Vibraphone",
    "Marimba", "Xylophone", "Tubular Bells", "Dulcimer",
    "Drawbar Organ", "Percussive Organ", "Rock Organ", "Church Organ",
    "Reed Organ", "Accordion", "Harmonica", "Tango Accordion",
    "Acoustic Guitar (nylon)", "Acoustic Guitar (steel)", "Electric Guitar (jazz)", "Electric Guitar (clean)",
    "Electric Guitar (muted)", "Overdriven Guitar", "Distortion Guitar", "Guitar Harmonics",
    "Acoustic Bass", "Electric Bass (finger)", "Electric Bass (pick)", "Fretless Bass",
    "Slap Bass 1", "Slap Bass 2", "Synth Bass 1", "Synth Bass 2",
    "Violin", "Viola", "Cello", "Contrabass",
    "Tremolo Strings", "Pizzicato Strings", "Orchestral Harp", "Timpani",
    "String Ensemble 1", "String Ensemble 2", "SynthStrings 1", "SynthStrings 2",
    "Choir Aahs", "Voice Oohs", "Synth Voice", "Orchestra Hit",
    "Trumpet", "Trombone", "Tuba", "Muted Trumpet",
    "French Horn", "Brass Section", "SynthBrass 1", "SynthBrass 2",
    "Soprano Sax", "Alto Sax", "Tenor Sax", "Baritone Sax",
    "Oboe", "English Horn", "Bassoon", "Clarinet",
    "Piccolo", "Flute", "Recorder", "Pan Flute",
    "Blown Bottle", "Shakuhachi", "Whistle", "Ocarina",
    "Lead 1 (square)", "Lead 2 (sawtooth)", "Lead 3 (calliope)", "Lead 4 (chiff)",
    "Lead 5 (charang)", "Lead 6 (voice)", "Lead 7 (fifths)", "Lead 8 (bass + lead)",
    "Pad 1 (new age)", "Pad 2 (warm)", "Pad 3 (polysynth)", "Pad 4 (choir)",
    "Pad 5 (bowed)", "Pad 6 (metallic)", "Pad 7 (halo)", "Pad 8 (sweep)",
    "FX 1 (rain)", "FX 2 (soundtrack)", "FX 3 (crystal)", "FX 4 (atmosphere)",
    "FX 5 (brightness)", "FX 6 (goblins)", "FX 7 (echoes)", "FX 8 (sci-fi)",
    "Sitar", "Banjo", "Shamisen", "Koto",
    "Kalimba", "Bag pipe", "Fiddle", "Shanai",
    "Tinkle Bell", "Agogo", "Steel Drums", "Woodblock",
    "Taiko Drum", "Melodic Tom", "Synth Drum", "Reverse Cymbal",
    "Guitar Fret Noise", "Breath Noise", "Seashore", "Bird Tweet",
    "Telephone Ring", "Helicopter", "Applause", "Gunshot",
]


def program_name(program: int) -> str:
    p = int(program)
    return GM_PROGRAMS[p] if 0 <= p < len(GM_PROGRAMS) else f"Program {p}"


def _pretty_midi():
    import pretty_midi  # type: ignore
    return pretty_midi


def analyze_midi(path: str | Path) -> dict:
    """解析 .mid, 返回轨清单与整体信息。不做选择。"""
    import pretty_midi  # noqa

    pm = _pretty_midi().PrettyMIDI(str(path))
    # tempo 估计: 取该 MIDI 最常见/首个有效 tempo
    tempi = []
    if pm.get_tempo_changes()[1].size:
        tempi = list(pm.get_tempo_changes()[1])
    bpm_est = float(tempi[0]) if tempi else 120.0
    # 过滤无音符的轨(如 conductor/歌词)
    tracks = []
    for i, inst in enumerate(pm.instruments):
        notes = inst.notes
        if not notes:
            continue
        dur = max((n.end for n in notes), default=0.0)
        tracks.append({
            "idx": i,
            "program": int(inst.program),
            "name": program_name(int(inst.program)) + ((" #%d" % (i + 1)) if i > 0 else ""),
            "is_drum": bool(inst.is_drum),
            "note_count": len(notes),
            "lowest_midi": min((n.pitch for n in notes), default=0),
            "highest_midi": max((n.pitch for n in notes), default=0),
            "duration_s": round(dur, 3),
        })
    total_dur = pm.get_end_time()
    return {
        "file": Path(path).name,
        "tempo_bpm": round(bpm_est, 2),
        "duration_s": round(total_dur, 3),
        "track_count": len(tracks),
        "tracks": tracks,
    }


def selected_tracks_to_events(path: str | Path, selected_idx: list[int],
                              confidence: float = 1.0) -> tuple[list[dict], float]:
    """取 MIDI 中指定轨道的音符 -> 统一事件列表(含 freq/midi/velocity/program)。

    Returns (events, duration_s)。选中轨为空或均为鼓? 仍返回空 events(交给上层报错)。
    """
    import pretty_midi  # noqa

    pm = _pretty_midi().PrettyMIDI(str(path))
    wanted = set(int(i) for i in selected_idx)
    events: list[dict] = []
    dur = 0.0
    for i, inst in enumerate(pm.instruments):
        if i not in wanted or not inst.notes:
            continue
        for n in inst.notes:
            start = float(n.start)
            end = max(float(n.end), start + 0.01)
            dur = max(dur, end)
            events.append({
                "start_s": round(start, 4),
                "dur_s": round(max(0.01, end - start), 4),
                "freq": round(440.0 * 2 ** ((int(n.pitch) - 69) / 12.0), 2),
                "midi": int(n.pitch),
                "velocity": int(n.velocity),
                "confidence": round(float(confidence), 3),
                "program": int(inst.program),
                "track": int(i),
            })
    events.sort(key=lambda e: (e["start_s"], e["midi"]))
    return events, dur
