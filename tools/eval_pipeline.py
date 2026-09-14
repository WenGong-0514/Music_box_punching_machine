"""对任意音频跑识别引擎, 存事件JSON + 打印统计(用于引擎对比与谱面对照)。
用法: python tools/eval_pipeline.py <audio> [--engine basic_pitch|dsp] [--out out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import soundfile as sf

from server import engines
from server.audio_io import decode_audio_file


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--engine", default="basic_pitch")
    ap.add_argument("--out", default=None)
    ap.add_argument("--min-conf", type=float, default=0.10)
    args = ap.parse_args()

    audio = Path(args.audio)
    print(f"[1/3] 解码 {audio.name} …")
    x, sr = decode_audio_file(audio)
    dur = len(x) / sr
    print(f"      sr={sr} 时长={dur:.1f}s")
    td = Path(tempfile.gettempdir())
    wav = td / "eval_mono.wav"
    sf.write(str(wav), x, sr, subtype="PCM_16")

    print(f"[2/3] 引擎 {args.engine} …")
    params = {"min_amplitude": args.min_conf} if args.engine == "basic_pitch" else {
        "onset_threshold": 0.5, "max_polyphony": 3, "min_freq": 55, "max_freq": 2500}
    t0 = time.time()
    events = engines.transcribe_with(args.engine, str(wav), params)
    dt = time.time() - t0
    print(f"      {len(events)} 事件, 耗时 {dt:.1f}s")

    # 简单统计
    midis = sorted(69 + 12 * np.log2(np.array([e["freq"] for e in events], float) / 440.0))
    if midis:
        print(f"      音域: {midis[0]:.0f}..{midis[-1]:.0f} (MIDI)")
    from collections import Counter
    pc = Counter(int(round(m)) % 12 for m in midis)
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    print("      音级直方:", {names[k]: v for k, v in pc.most_common(6)})
    ons = np.array(sorted(e["start_s"] for e in events))
    if len(ons) > 1:
        gaps = np.diff(ons)
        print(f"      平均间隔 {gaps.mean():.3f}s 中位 {np.median(gaps):.3f}s")

    print(f"[3/3] 存 {args.out or '(未存)'}")
    if args.out:
        out = {"audio": str(audio), "engine": args.engine, "params": params,
               "duration_s": round(dur, 3), "events": events,
               "elapsed_s": round(dt, 2)}
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
