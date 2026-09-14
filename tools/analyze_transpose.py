"""分析移调对 30 音适配的影响(供文档/调试)。"""
import json
import sys

sys.path.insert(0, r"D:\grbl_dev")

from server.notetable import load_note_table  # noqa: E402
from server.quantize import quantize_to_tape  # noqa: E402

table = load_note_table(r"D:\grbl_dev\data\note_table_30note.json")
d = json.load(open(r"D:\grbl_dev\tools\score_ref\omni_events.json", encoding="utf-8"))
ev = d["events"]
print("=== 各固定移调: kept(总保留) / fold / dup ===")
for s in range(-24, 25):
    _t, st = quantize_to_tape(ev, table, bpm=111, steps_per_beat=8,
                              out_of_range="fold", transpose_semitones=s, auto_transpose=0)
    print(f"shift {s:+3d}: kept={st['kept']:4d} fold={st['folded']:4d} "
          f"dup={st['duplicates']:3d} skip={st['out_of_range_skipped']:3d}")
print("=== 自动移调(±24) ===")
_t, st = quantize_to_tape(ev, table, bpm=111, steps_per_beat=8,
                          out_of_range="fold", auto_transpose=24)
print("auto shift:", st["transpose_used"])
print({k: st[k] for k in ("kept", "folded", "duplicates",
                          "out_of_range_skipped", "final_holes")})
