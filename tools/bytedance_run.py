"""Bytedance piano-transcription-inference (Note_pedal, MAESTRO F1=0.9677) 运行器。

用法: python tools/bytedance_run.py <wav|mp3> [--out xxx.json]
权重(~165MB)首次自动下载到 ~/piano_transcription_inference_data/ (Zenodo)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CKPT_NAME = "note_F1=0.9677_pedal_F1=0.9186.pth"
CKPT_URL = ("https://zenodo.org/record/4034264/files/"
            "CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1")
CKPT_PATH = Path.home() / "piano_transcription_inference_data" / CKPT_NAME


def ensure_ckpt() -> Path:
    CKPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CKPT_PATH.exists() or CKPT_PATH.stat().st_size < 1.6e8:
        print("[1/4] 下载模型权重(165MB) …")
        req = urllib.request.Request(CKPT_URL, headers={"User-Agent": "x"})
        with urllib.request.urlopen(req, timeout=1800) as r, open(CKPT_PATH, "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
        print("      完成:", CKPT_PATH)
    return CKPT_PATH


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.exists():
        print("audio 不存在:", audio)
        return 2

    ck = ensure_ckpt()
    # omnizart 风格: wav 输入; 非 wav 先转
    import soundfile as sf
    if audio.suffix.lower() != ".wav":
        x, sr = sf.read(str(audio), dtype="float32")
        td = Path(tempfile.gettempdir())
        wav = td / "bytedance_input.wav"
        sf.write(str(wav), x, sr, subtype="PCM_16")
    else:
        wav = audio

    print("[2/4] 加载模型(CPU) …")
    t0 = time.time()
    import torch
    from piano_transcription_inference import PianoTranscription
    device = torch.device("cpu")
    pt = PianoTranscription(model_type="Note_pedal", checkpoint_path=str(ck), device=device)
    print(f"      模型就绪 {time.time() - t0:.0f}s")

    print("[3/4] 转录中 …")
    x, sr = sf.read(str(wav), dtype="float32")
    if x.ndim == 2:
        x = x.mean(axis=1)
    import librosa
    # bytedance 模型输入采样率为 16k, 必须重采样
    if sr != 16000:
        x = librosa.resample(x, orig_sr=sr, target_sr=16000)
        sr = 16000
    midi_path = str(Path(tempfile.gettempdir()) / "bytedance_out.mid")
    t1 = time.time()
    result = pt.transcribe(x.astype("float32"), midi_path=midi_path)
    dt = time.time() - t1
    print(f"      转录耗时 {dt:.0f}s; keys={list(result.keys())}")
    use = None
    try:
        import pretty_midi
        use = pretty_midi.PrettyMIDI(midi_path)
    except Exception as e:
        print("      midi 解析失败:", e)
    print("[4/4] 解析音符 …")
    events = []
    if use is not None:
        for inst in use.instruments:
            for note in inst.notes:
                events.append({
                    "start_s": round(float(note.start), 4),
                    "dur_s": round(max(0.01, float(note.end) - float(note.start)), 4),
                    "freq": round(440.0 * (2.0 ** ((note.pitch - 69) / 12.0)), 2),
                    "midi": note.pitch,
                    "velocity": note.velocity,
                })
    events.sort(key=lambda e: e["start_s"])
    print(f"      {len(events)} 音符事件")
    if args.out:
        dur_s = float(sf.info(str(audio)).duration)
        out = {"audio": str(audio), "engine": "bytedance_piano_transcription",
               "duration_s": round(dur_s, 3), "elapsed_s": round(dt, 1), "events": events}
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print("      存", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
