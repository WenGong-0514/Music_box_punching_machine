"""端到端冒烟测试(命令行, 无 GUI):
  MP3导入解码 -> Basic Pitch / DSP 识别 -> 30音量化 -> 纸带校验 -> 导出。
用法: python tools/e2e_check.py [--engine dsp|basic_pitch]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import engines  # noqa: E402
from server.audio_io import decode_audio_file  # noqa: E402
from server.notetable import load_note_table  # noqa: E402
from server.quantize import quantize_to_tape  # noqa: E402
from server.tape import Tape  # noqa: E402

MEDIA = ROOT / "tools" / "media"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="basic_pitch", choices=["basic_pitch", "dsp", "all"])
    ap.add_argument("--audio", default=None, help="自定义音频文件")
    args = ap.parse_args()

    audio = Path(args.audio) if args.audio else (MEDIA / "twinkle_30note.mp3")
    if not audio.exists():
        print(f"[!] 缺少测试音频 {audio}, 先运行 tools/make_test_audio.py")
        return 2

    print(f"[1/5] 解码 {audio.name} …")
    x, sr = decode_audio_file(audio)
    print(f"      sr={sr} 时长={len(x) / sr:.2f}s")
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "mono.wav"
        import soundfile as sf
        sf.write(str(wav), x, sr, subtype="PCM_16")

        table = load_note_table(ROOT / "data" / "note_table_30note.json")
        print("[2/5] 音表:", table.name, " 列数", len(table.columns),
              " 最低", table.columns[0].name, table.columns[0].midi,
              " 最高", table.columns[-1].name, table.columns[-1].midi)

        engines_list = ["basic_pitch", "dsp"] if args.engine == "all" else [args.engine]
        for eid in engines_list:
            info = next((e for e in engines.available_engines() if e["id"] == eid), None)
            if not info or not info["available"]:
                print(f"[!] 引擎 {eid} 不可用, 跳过")
                continue
            print(f"[3/5] 引擎 {eid}: 识别中 …")
            t0 = time.time()
            params = {"min_amplitude": 0.05} if eid == "basic_pitch" else {
                "onset_threshold": 0.5, "max_polyphony": 3, "min_freq": 65, "max_freq": 2500}
            events = engines.transcribe_with(eid, str(wav), params)
            dt = time.time() - t0
            print(f"      -> {len(events)} 个音符事件, 耗时 {dt:.1f}s")
            if not events:
                print("      [!] 无音符, 中止")
                continue
            for ev in events[:8]:
                print(f"      t={ev['start_s']:.2f}s dur={ev['dur_s']:.2f} "
                      f"f={ev['freq']:.1f}Hz conf={ev['confidence']:.2f}")

            print("[4/5] 量化 → 纸带")
            tape, stats = quantize_to_tape(events, table, bpm=120.0, steps_per_beat=8,
                                           min_confidence=0.0, out_of_range="fold")
            print(f"      stats: {stats}")
            rows = tape.max_row() + 1
            print(f"      孔数={tape.hole_count()} 行数={rows} 时长≈{tape.duration_seconds():.1f}s")
            assert tape.hole_count() > 0, "纸带不应为空"
            # 校验: 折叠策略下不应有超范围丢失
            if eid == "basic_pitch":
                assert stats["out_of_range_skipped"] <= len(events) * 0.1, "折叠策略异常"

            print("[5/5] 导出格式校验")
            j = tape.to_json()
            csv = tape.to_csv()
            svg = tape.to_svg(table)
            assert '"holes"' in j and csv.startswith("# bpm=") and svg.startswith("<svg")
            print(f"      JSON {len(j)}B / CSV {len(csv)}B / SVG {len(svg)}B  OK")
            print("=" * 46)

    print("E2E 通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
