"""DSP 回退引擎: 纯 numpy/scipy 实现 (onset 分段 + 谐波求和多音估计)。

精度有限, 面向旋律 + 简单和弦; 单声部/纯音乐效果较好。
"""
from __future__ import annotations

import numpy as np
import soundfile as sf
from scipy import signal

NPERSEG = 2048
HOP = 512
DEFAULT_MIN_FREQ = 65.0      # 略低于音表最低音 C3≈130Hz 一个八度, 便于折叠
DEFAULT_MAX_FREQ = 2500.0


def transcribe(wav_path: str, params: dict, progress=None) -> list[dict]:
    x, sr = sf.read(wav_path, dtype="float32", always_2d=False)
    if x.ndim == 2:
        x = x.mean(axis=1)
    x = np.nan_to_num(x.astype(np.float32))
    if len(x) == 0:
        return []

    min_freq = float(params.get("min_freq", DEFAULT_MIN_FREQ))
    max_freq = float(params.get("max_freq", DEFAULT_MAX_FREQ))
    onset_thresh = float(params.get("onset_threshold", 0.45))
    max_poly = int(params.get("max_polyphony", 3))
    min_note_dur = float(params.get("min_note_dur_s", 0.045))

    f, t, Z = signal.stft(x, fs=sr, nperseg=NPERSEG, noverlap=NPERSEG - HOP,
                          window="hann", boundary=None, padded=False)
    mag = np.abs(Z)                       # (n_freq, n_frame)
    if progress:
        progress(0.1, "检测起点…")

    # ---- 起点检测: 频谱通量 ----
    log_mag = np.log1p(mag)
    flux = np.maximum(0.0, np.diff(log_mag, axis=1))
    flux = flux.mean(axis=0)              # (n_frame-1,)
    flux = np.concatenate([flux, [0.0]])
    # 平滑
    kern = np.hanning(7)
    kern /= kern.sum()
    flux_s = np.convolve(flux, kern, mode="same")
    med = np.median(flux_s) + 1e-9
    height = onset_thresh * med
    dist = max(1, int(round(0.09 * sr / HOP)))       # 相邻起点最小间隔 90ms
    peaks, props = signal.find_peaks(flux_s, height=height, distance=dist,
                                     prominence=height * 0.5)
    boundaries = [0]
    boundaries.extend(int(p) for p in peaks)
    boundaries.append(mag.shape[1] - 1)

    # ---- 逐段多音估计 ----
    if progress:
        progress(0.3, "分段分析中…")
    freq_grid, _ = _log_grid(min_freq, max_freq, bins_per_octave=24)
    events: list[dict] = []
    n_seg = len(boundaries) - 1
    bin_hz = sr / NPERSEG
    max_harm = 10

    for si in range(n_seg):
        a, b = boundaries[si], boundaries[si + 1]
        seg_len = (b - a + 1) * HOP / sr
        if seg_len < min_note_dur:
            continue
        seg_mag = mag[:, a:b + 1].mean(axis=1)        # (n_freq,)
        idx_by_freq = (freq_grid / bin_hz).astype(int)  # 每候选基频对应的频点索引(基波)
        # 谐波求和: score(f0) = sum_h mag[h*f0]/h
        nyq_idx = mag.shape[0] - 1
        score = np.zeros(len(freq_grid), dtype=np.float64)
        for h in range(1, max_harm + 1):
            fi = (freq_grid * h / bin_hz).astype(int)
            valid = fi <= nyq_idx
            score[valid] += seg_mag[fi[valid]] / h
        score = np.log1p(score)
        # 归一化置信
        if score.max() <= 0:
            continue
        gate = max(score.max() * 0.35, np.median(score))
        # 选局部极大(间隔 >= 2 个半音格)
        min_gap = 4   # 24 bpo 下 2 半音
        order = np.argsort(score)[::-1]
        picked: list[int] = []
        for k in order:
            if score[k] < gate:
                continue
            ok = all(abs(k - q) >= min_gap for q in picked)
            if ok:
                picked.append(k)
            if len(picked) >= max_poly:
                break
        for k in picked:
            events.append({
                "start_s": round(a * HOP / sr, 4),
                "dur_s": round(seg_len, 4),
                "freq": round(float(freq_grid[k]), 2),
                "confidence": round(float(min(1.0, score[k] / score.max())), 4),
            })
        if progress and si % max(1, n_seg // 10) == 0:
            progress(0.3 + 0.6 * (si + 1) / max(1, n_seg), f"分段 {si + 1}/{n_seg}")

    events.sort(key=lambda e: e["start_s"])
    if progress:
        progress(1.0, f"完成: {len(events)} 个音符")
    return events


def _log_grid(fmin: float, fmax: float, bins_per_octave: int) -> tuple[np.ndarray, int]:
    n = int(np.ceil(bins_per_octave * np.log2(fmax / fmin))) + 1
    f = fmin * 2.0 ** (np.arange(n) / bins_per_octave)
    return f, n
