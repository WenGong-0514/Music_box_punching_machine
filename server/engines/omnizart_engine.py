"""Omnizart 引擎: music_piano-v2 (MAESTRO 训练的钢琴专用转录, U-Net)。

模型/权重固化于 third_party/omnizart (85MB)。运行时需要 TensorFlow + tf_keras(Keras2):
omnizart 源码已把显式 tensorflow.keras 导入改写为 tf_keras, 调用前再把 tf.keras 指向
tf_keras, 以兼容 Keras2 时代保存的 SavedModel。

注意: 加载 TF 需 ~10-20s, 整曲转录一首 3 分钟钢琴曲约 1-3 分钟(CPU)。
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import threading
from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent.parent / "third_party" / "omnizart"
_CKPT_DEFAULT = "music_piano-v2"
_lock = threading.Lock()
_app = None


def is_available() -> bool:
    return (_PKG / "checkpoints" / "music" / _CKPT_DEFAULT / "saved_model.pb").exists()


def _ensure_app():
    global _app
    with _lock:
        if _app is None:
            os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
            import tensorflow as tf  # noqa
            # third_party/omnizart 本身就是 omnizart 包 -> 把其父目录加入 sys.path
            if str(_PKG.parent) not in sys.path:
                sys.path.insert(0, str(_PKG.parent))
            from omnizart.music.app import MusicTranscription  # noqa
            import tf_keras  # noqa
            # 老代码中 tf.keras.* 用法需 keras2; 显式导入已被改写为 tf_keras
            tf.keras = tf_keras
            _app = MusicTranscription()
    return _app


def transcribe(wav_path: str, params: dict, progress=None) -> list[dict]:
    app = _ensure_app()
    if progress:
        progress(0.15, "Omnizart 引擎加载中…")
    model = str(params.get("model", _CKPT_DEFAULT))
    ckpt = _PKG / "checkpoints" / "music" / model
    if not (ckpt / "saved_model.pb").exists():
        raise RuntimeError(f"找不到 Omnizart 模型: {ckpt}")
    out_dir = Path(tempfile.mkdtemp(prefix="omni_"))
    if progress:
        progress(0.35, "特征提取与推理中(整曲约1-3分钟)…")
    midi = app.transcribe(str(wav_path), model_path=str(ckpt), output=str(out_dir))
    if progress:
        progress(0.95, "解析音符…")
    events = []
    for inst in midi.instruments:
        for note in inst.notes:
            midi_n = note.pitch
            events.append({
                "start_s": round(float(note.start), 4),
                "dur_s": round(max(0.01, float(note.end) - float(note.start)), 4),
                "freq": round(440.0 * (2.0 ** ((midi_n - 69) / 12.0)), 2),
                "confidence": round(max(0.0, min(1.0, note.velocity / 127.0)), 4),
            })
    events.sort(key=lambda e: e["start_s"])
    if progress:
        progress(1.0, f"完成: {len(events)} 个音符")
    return events
