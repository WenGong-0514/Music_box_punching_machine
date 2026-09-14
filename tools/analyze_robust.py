import json
import sys

sys.path.insert(0, r"D:\grbl_dev")

from server.notetable import load_note_table  # noqa: E402
from server.quantize import quantize_to_tape  # noqa: E402

table = load_note_table(r"D:\grbl_dev\data\note_table_30note.json")
for name in ("omni_piano6s_events", "omni_events"):
    d = json.load(open(rf"D:\grbl_dev\tools\score_ref\{name}.json", encoding="utf-8"))
    for robust in (False, True):
        _t, st = quantize_to_tape(d["events"], table, bpm=111, steps_per_beat=8,
                                  out_of_range="fold", auto_transpose=24,
                                  shift_robust=robust)
        print(f"{name} robust={robust}: shift={st['transpose_used']:+d} "
              f"fold={st['folded']} holes={st['final_holes']} "
              f"ext_hi={st['extreme_high']} ext_lo={st['extreme_low']}")
