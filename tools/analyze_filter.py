import json
import sys

sys.path.insert(0, r"D:\grbl_dev")

from server.notetable import load_note_table  # noqa: E402
from server.quantize import quantize_to_tape  # noqa: E402

table = load_note_table(r"D:\grbl_dev\data\note_table_30note.json")
d = json.load(open(r"D:\grbl_dev\tools\score_ref\omni_piano6s_events.json", encoding="utf-8"))
for cap in (127, 96, 92, 88):
    _t, st = quantize_to_tape(d["events"], table, bpm=111, steps_per_beat=8,
                              out_of_range="fold", auto_transpose=24,
                              shift_robust=True, max_midi=cap)
    print(f"cap={cap}: shift={st['transpose_used']:+d} fold={st['folded']} "
          f"holes={st['final_holes']} reg_drop={st['register_dropped']} "
          f"ext_hi={st['extreme_high']}")
