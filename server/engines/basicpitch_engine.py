"""Basic Pitch 引擎: Spotify 开源多音高识别 (ICASSP2022), 优先 ONNX 运行时。

安装(Windows/py3.12, 避免拖入 TensorFlow):
    pip install <basic_pitch-0.4.0-py2.py3-none-any.whl> --no-deps
    pip install mir-eval pretty-midi "resampy<0.4.3"
依赖已随 basic_pitch 0.4.0 捆绑 nmp.onnx 模型; 仅装 onnxruntime 时
inference 自动选择 ONNX 后端。

API 兼容 0.3(NoteEvent 对象) 与 0.4(元组, pitch 为 MIDI)。
"""
from __future__ import annotations

import functools
import math

_MODULE = None
_ENGINE_ERR = ""
_model_cache = None


def _load() -> bool:
    global _MODULE, _ENGINE_ERR
    if _MODULE is not None or _ENGINE_ERR:
        return _MODULE is not None
    try:
        import basic_pitch.inference as bpi  # noqa
        _MODULE = bpi
    except Exception as e:  # pragma: no cover
        _ENGINE_ERR = f"{e.__class__.__name__}: {e}"
    return _MODULE is not None


def _get_model(device: str = "cpu"):
    """强制使用 ONNX 模型文件(即便检测到 TensorFlow, 也避免其走 TF SavedModel 路径)。
    device: cpu | dml | auto —— dml/auto 用 DirectML 走 AMD/Intel 显卡(需 onnxruntime-directml)。
    """
    global _model_cache
    if _model_cache is None:
        try:
            import pathlib
            import basic_pitch
            onnx_path = (pathlib.Path(basic_pitch.__file__).parent /
                         "saved_models" / "icassp_2022" / "nmp.onnx")
            if not onnx_path.exists():
                from basic_pitch import ICASSP_2022_MODEL_PATH
                onnx_path = ICASSP_2022_MODEL_PATH
            import onnxruntime as ort
            providers = ["CPUExecutionProvider"]
            if device in ("dml", "auto") and "DmlExecutionProvider" in ort.get_available_providers():
                providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
            # basic_pitch.Model 内部写死 CPUExecutionProvider -> 包装 InferenceSession
            import basic_pitch.inference as bpi
            _real = ort.InferenceSession

            def _session(*a, **kw):
                kw["providers"] = providers
                return _real(*a, **kw)

            bpi.ort.InferenceSession = _session
            _model_cache = _MODULE.Model(onnx_path)
        except Exception as e:
            raise RuntimeError(f"模型加载失败: {e}")
    return _model_cache


def _unpack(ne):
    """兼容两种 note event 表示, 返回 (start_s, end_s, freq_hz, amplitude)。"""
    if hasattr(ne, "start_time"):      # 0.3.x NoteEvent namedtuple(pitch=Hz)
        f = float(ne.pitch)
        return float(ne.start_time), float(ne.end_time), f, float(ne.amplitude)
    start, end, pitch_midi, amp = float(ne[0]), float(ne[1]), float(ne[2]), float(ne[3])
    f = 440.0 * (2.0 ** ((pitch_midi - 69.0) / 12.0))   # 0.4.x: pitch 为 MIDI
    return start, end, f, amp


def _midi_to_freq(m):
    return 440.0 * (2.0 ** ((m - 69.0) / 12.0))


def transcribe(wav_path: str, params: dict, progress=None) -> list[dict]:
    if not _load():
        raise RuntimeError(_ENGINE_ERR or "Basic Pitch 不可用")
    min_amp = float(params.get("min_amplitude", 0.10))
    device = str(params.get("device", "cpu"))  # cpu | dml | auto
    onset_th = float(params.get("onset_threshold", 0.5))
    frame_th = float(params.get("frame_threshold", 0.3))
    min_note_ms = float(params.get("minimum_note_length_ms", 80.0))
    min_f = params.get("min_freq") or None
    max_f = params.get("max_freq") or None
    if progress:
        progress(0.05, f"加载 ONNX 模型({device})…")
    import inspect
    sig = inspect.signature(_MODULE.predict)
    kw = "model_or_model_path" if "model_or_model_path" in sig.parameters else "model"
    kwargs = {kw: _get_model(device)}
    _model_output, _midi_data, note_events = _MODULE.predict(
        str(wav_path),
        **kwargs,
        onset_threshold=onset_th,
        frame_threshold=frame_th,
        minimum_note_length=min_note_ms,
        minimum_frequency=min_f,
        maximum_frequency=max_f,
    )
    events = []
    for ne in note_events:
        try:
            start, end, freq, amp = _unpack(ne)
        except Exception:
            continue
        if amp < min_amp:
            continue
        if min_f and freq < min_f:
            continue
        if max_f and freq > max_f:
            continue
        events.append({
            "start_s": round(start, 4),
            "dur_s": round(max(0.01, end - start), 4),
            "freq": round(freq, 2),
            "confidence": round(float(amp), 4),
        })
    events.sort(key=lambda e: e["start_s"])
    if progress:
        progress(1.0, f"完成: {len(events)} 个音符")
    return events
