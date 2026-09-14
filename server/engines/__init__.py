"""识别引擎包。basic_pitch(多音高深度模型, 主力) + dsp(轻量回退)。
engines 输入统一为解码后 wav 文件路径, 输出统一事件结构:
    [{"start_s": float, "dur_s": float, "freq": float(Hz), "confidence": float}]
"""
from __future__ import annotations


def note_name_of_freq(freq: float) -> str:
    import math
    if freq <= 0:
        return "?"
    midi = 69 + 12 * (math.log(freq / 440.0) / math.log(2.0))
    m = int(round(midi))
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[m % 12]}{m // 12 - 1}"


def available_engines() -> list[dict]:
    out = []
    try:
        import basic_pitch  # noqa: F401
        bp = {"id": "basic_pitch", "name": "Basic Pitch(深度多音模型, 推荐)",
              "available": True, "hint": "多声部识别效果好, 首次运行需加载模型"}
    except Exception as e:
        bp = {"id": "basic_pitch", "name": "Basic Pitch(深度多音模型)",
              "available": False, "hint": f"未安装: pip install basic-pitch ({e.__class__.__name__})"}
    out.append(bp)
    out.append({"id": "dsp", "name": "DSP 频谱引擎(轻量, 无需额外依赖)",
                "available": True, "hint": "旋律/和弦块级识别, 精度低于 Basic Pitch"})
    # Omnizart: 现改由 HTTP "引擎服务"提供(本机不 import TF)。可用性=服务可达且就绪。
    try:
        from . import remote_omnizart
        omz = dict(remote_omnizart.status())
        # 补 GUI/badge 共用的字段
        omz["name"] = omz.get("name") or "Omnizart(music_piano-v2; HTTP 服务)"
        omz["id"] = omz.get("id", "omnizart")
        omz["kind"] = omz.get("kind", "service")
        # 若无服务/不可达, 给出明确 reason(旧版仅查 checkpoint 会假 ✓)
        if not omz.get("available"):
            omz.setdefault("reason", "未配置可用 Omnizart 服务")
        out.append(omz)
    except Exception as e:  # pragma: no cover
        out.append({"id": "omnizart", "name": "Omnizart(music_piano-v2)",
                    "available": False, "kind": "service",
                    "reason": f"远端模块异常: {e}"})
    return out


def transcribe_with(engine_id: str, wav_path: str, params: dict,
                    progress=None) -> list[dict]:
    """调度到具体引擎。progress: callable(percent: float, msg: str) 可选。"""
    if engine_id == "basic_pitch":
        from . import basicpitch_engine
        return basicpitch_engine.transcribe(wav_path, params, progress)
    if engine_id == "dsp":
        from . import dsp_engine
        return dsp_engine.transcribe(wav_path, params, progress)
    if engine_id == "omnizart":
        # Omnizart 只经 HTTP 服务(引擎运行在能跑它的机器/容器上)
        from . import remote_omnizart
        if not remote_omnizart.available():
            raise RuntimeError(f"Omnizart 服务不可用: {remote_omnizart.status().get('reason')}")
        return remote_omnizart.transcribe(wav_path, params, progress)
    raise ValueError(f"未知引擎: {engine_id}")
