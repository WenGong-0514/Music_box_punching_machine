"""用 Omnizart(music_piano-v2, MAESTRO训练的钢琴转录)识别音频, 输出统一事件JSON。

用法: python tools/omnizart_run.py <audio> [--ckpt music_piano-v2] [--out xxx.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OMNI_SRC = ROOT / "third_party" / "omnizart"

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("OMP_NUM_THREADS", "4")


def load_omnizart():
    import tensorflow as tf
    # third_party/omnizart 目录即 omnizart 包; 父目录加入 sys.path 才能 import omnizart
    parent = OMNI_SRC.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
    from omnizart.music.app import MusicTranscription
    # omnizart 老代码仍通过 tf.keras.* 构建/加载(keras2 时代 API):
    # 先把 tf.keras 指到 tf_keras(keras2); 其源码中显式 tensorflow.keras 导入已改写为 tf_keras。
    import tf_keras  # noqa
    tf.keras = tf_keras
    return MusicTranscription()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--ckpt", default="music_piano-v2",
                    choices=["music_piano", "music_piano-v2", "music_pop", "music_note_stream"])
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.exists():
        print("audio not exist:", audio)
        return 2

    # omnizart 输入必须是 wav
    import tempfile
    import soundfile as sf
    dur_s = float(sf.info(str(audio)).duration)
    if audio.suffix.lower() != ".wav":
        x, sr = sf.read(str(audio), dtype="float32")
        td = Path(tempfile.gettempdir())
        wav = td / "omni_input.wav"
        sf.write(str(wav), x, sr, subtype="PCM_16")
    else:
        wav = audio

    ckpt = OMNI_SRC / "checkpoints" / "music" / args.ckpt
    if not (ckpt / "saved_model.pb").exists():
        print("checkpoint missing:", ckpt)
        return 2

    print(f"[1/3] 加载 Omnizart 模型 {args.ckpt} …")
    t0 = time.time()
    app = load_omnizart()
    print(f"      加载引擎 {time.time() - t0:.0f}s")

    print("[2/3] 转录中(可能较慢)…")
    t1 = time.time()
    out_dir = Path(tempfile.gettempdir()) / "omni_out"
    out_dir.mkdir(exist_ok=True)
    midi = app.transcribe(str(wav), model_path=str(ckpt), output=str(out_dir))
    dt = time.time() - t1
    print(f"      转录耗时 {dt:.0f}s")

    print("[3/3] 解析 MIDI 音符 …")
    events = []
    for inst in midi.instruments:
        prog = inst.program
        for note in inst.notes:
            events.append({
                "start_s": round(note.start, 4),
                "dur_s": round(max(0.01, note.end - note.start), 4),
                "freq": round(440.0 * 2 ** ((note.pitch - 69) / 12.0), 2),
                "midi": note.pitch,
                "velocity": note.velocity,
                "program": prog,
            })
    events.sort(key=lambda e: e["start_s"])
    print(f"      {len(events)} 音符事件")

    progs = {}
    for e in events:
        progs[e["program"]] = progs.get(e["program"], 0) + 1
    print("      program 分布:", progs)

    if args.out:
        out = {"audio": str(audio), "engine": "omnizart", "ckpt": args.ckpt,
               "duration_s": round(dur_s, 3),
               "elapsed_s": round(dt, 1), "events": events}
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print("      存", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
