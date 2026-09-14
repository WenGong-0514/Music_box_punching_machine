"""音频解码: 各类输入 -> 单声道 float32 numpy (16k~44.1k 均可)。

顺序: 优先 miniaudio(纯pip, 免外部程序); 无则用 ffmpeg 命令行; 
soundfile 直接支持 wav/flac/ogg。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np

try:
    import miniaudio  # type: ignore
    HAS_MINI = True
except Exception:
    HAS_MINI = False

import soundfile as sf

SUPPORTED_EXT = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".mp4", ".webm"}


class AudioDecodeError(Exception):
    pass


def _to_mono_float(data: np.ndarray, sr: int) -> np.ndarray:
    x = np.asarray(data, dtype=np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    x = np.nan_to_num(x)
    if np.max(np.abs(x)) > 0:
        x = x / max(1e-9, float(np.max(np.abs(x))))
    return x.astype(np.float32), sr


def decode_miniaudio(path: Path):
    info = miniaudio.get_file_info(str(path))
    nch = info.nchannels
    sr = info.sample_rate
    dec = miniaudio.decode_file(str(path), output_format=miniaudio.SampleFormat.FLOAT32,
                                nchannels=nch, sample_rate=sr)
    # decode_file 返回流式对象
    frames = []
    for chunk in dec:
        frames.append(chunk.samples if hasattr(chunk, "samples") else chunk)
    data = np.concatenate(frames) if frames else np.zeros(0, np.float32)
    if nch > 1:
        data = data.reshape(-1, nch)
    return data, sr


def decode_ffmpeg(path: Path, target_sr: int = 22050) -> tuple[np.ndarray, int]:
    """用 ffmpeg 解码为 wav 到临时文件再用 soundfile 读取。"""
    import shutil
    exe = shutil.which("ffmpeg")
    if not exe:
        raise AudioDecodeError("未找到 ffmpeg, 无法解码该格式(请安装 ffmpeg 或改用 wav)")
    with tempfile.TemporaryDirectory(prefix="mbtape_") as td:
        out = Path(td) / "decoded.wav"
        r = subprocess.run([exe, "-y", "-i", str(path), "-ac", "1",
                            "-ar", str(target_sr), "-f", "wav", str(out)],
                           capture_output=True)
        if r.returncode != 0 or not out.exists():
            raise AudioDecodeError(f"ffmpeg 解码失败: {r.stderr.decode(errors='ignore')[-200:]}")
        data, sr = sf.read(str(out), dtype="float32", always_2d=False)
    return _to_mono_float(data, sr)


def decode_audio_file(path: str | Path, target_sr: int = 22050) -> tuple[np.ndarray, int]:
    """解码任意支持的音频文件, 返回 (单声道 float32 归一化, 采样率)。"""
    p = Path(path)
    if not p.exists():
        raise AudioDecodeError(f"文件不存在: {p}")
    ext = p.suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise AudioDecodeError(f"不支持的格式 {ext}(支持: {sorted(SUPPORTED_EXT)})")

    # 1) soundfile 直接支持
    try:
        data, sr = sf.read(str(p), dtype="float32", always_2d=False)
        return _to_mono_float(data, sr)
    except Exception:
        pass

    # 2) miniaudio (mp3/m4a/ogg...)
    if HAS_MINI:
        try:
            data, sr = decode_miniaudio(p)
            return _to_mono_float(data, sr)
        except Exception:
            pass

    # 3) ffmpeg 兜底
    return decode_ffmpeg(p, target_sr)


def make_waveform_peaks(x: np.ndarray, sr: int, bins: int = 2000) -> list[dict]:
    """预计算波形 min/max 包络, 供前端画波形(避免传整段音频)。"""
    n = len(x)
    if n == 0:
        return []
    step = max(1, n // bins)
    out = []
    for i in range(0, n, step):
        seg = x[i:i + step]
        if len(seg) == 0:
            break
        out.append({"t": round(i / sr, 3),
                    "min": round(float(np.min(seg)), 4),
                    "max": round(float(np.max(seg)), 4)})
    return out
