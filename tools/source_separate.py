"""Demucs 源分离工具 (htdemucs 4-stems: drums/bass/other/vocals)。

用法:
  python tools/source_separate.py <音频> --out <目录> [--device dml|cpu] [--model htdemucs]
GPU(AMD/Intel): torch-directml => --device dml (RX6900XT等)。
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STEMS = ["drums", "bass", "other", "vocals"]


def load_audio(audio: Path) -> tuple[torch.Tensor, int]:
    x, sr = sf.read(str(audio), dtype="float32", always_2d=True)
    if x.ndim == 1:
        x = x[:, None]
    else:
        x = x.T                      # (ch, n)
    return torch.from_numpy(x.astype(np.float32)), int(sr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--out", default=None)
    ap.add_argument("--device", default="dml", choices=["dml", "cpu"])
    ap.add_argument("--model", default="htdemucs")
    ap.add_argument("--shifts", type=int, default=1)
    ap.add_argument("--stems", default=None,
                    help="只保存指定声部(逗号分隔, 如 piano,vocals); 默认全部")
    args = ap.parse_args()

    audio = Path(args.audio)
    keep = set(s.strip() for s in args.stems.split(",")) if args.stems else None
    out_dir = Path(args.out) if args.out else ROOT / "tools" / "media" / "stems" / args.model
    out_dir.mkdir(parents=True, exist_ok=True)

    device = None
    if args.device == "dml":
        import torch_directml
        device = torch_directml.device()
        print("DML 设备:", torch_directml.device_name(0))
    else:
        device = torch.device("cpu")
        torch.set_num_threads(8)

    from demucs.pretrained import get_model
    print(f"[1/4] 下载/加载模型 {args.model} …")
    t0 = time.time()
    model = get_model(args.model)
    model.to(device)
    print(f"      模型就绪 {time.time() - t0:.0f}s")

    print("[2/4] 读取音频 …")
    wav, sr = load_audio(audio)
    if sr != model.samplerate:
        from demucs.audio import convert_audio
        wav = convert_audio(wav, sr, model.samplerate, model.audio_channels)
    print(f"      时长 {wav.shape[1] / model.samplerate:.1f}s @{model.samplerate}Hz")

    print(f"[3/4] 分离中(device={args.device})…")
    from demucs.apply import apply_model
    t1 = time.time()
    ref = wav.mean(0) if wav.shape[0] == 2 else wav[0]
    with torch.no_grad():
        sources = apply_model(model, wav[None], device=device, shifts=args.shifts,
                              split=True, overlap=0.25, progress=True)[0]
    dt = time.time() - t1
    print(f"      分离耗时 {dt:.0f}s")

    print("[4/4] 存分轨 + 能量统计 …")
    energies = {}
    names = model.sources if hasattr(model, "sources") else STEMS
    for i, stem in enumerate(names):
        s = sources[i]
        e = float(torch.mean(s ** 2))
        energies[stem] = round(e, 6)
        if keep and stem not in keep:
            print(f"      (跳过 {stem}.wav)")
            continue
        p = out_dir / f"{stem}.wav"
        sf.write(str(p), s.cpu().numpy().T, model.samplerate, subtype="PCM_16")
        print(f"      {stem}.wav  energy={e:.5f}")
    total = sum(energies.values()) or 1e-9
    print("      占比:", {k: f"{v / total * 100:.1f}%" for k, v in energies.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
