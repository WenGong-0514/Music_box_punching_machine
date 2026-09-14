#!/usr/bin/env python3
"""Omnizart HTTP 引擎服务 —— 把 music_piano-v2 暴露成可用 IP:port 调用转录.

协议(与上位机 GUI 约定一致):
    GET  /health   -> {"ok":true,"available":bool,"model":..,"device":cpu|gpu,"reason":""}
    POST /transcribe (multipart: file=wav, ckpt=music_piano-v2)
         ->200 events 数组(每项含 start_s,dur_s,freq,midi,velocity,confidence)

依赖: 一台能跑 Omar... 的标准环境(python3.11~3.12 + tensorflow* + tf_keras + omni包),
       omni 包路径通过环境变量 OMNI_PKG_PARENT(其父目录含 omnizart) 或本脚本同仓 third_party 指定.

启动(在能跑 Omnizart 的机器/Docker 里):
    python omni_http.py --port 8766         # 默认 0.0.0.0, 便于被 IP:port 调用
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

# ---- omnizart 包解析 -------------------------------------------------
def _resolve_pkg_parent() -> Path:
    if os.environ.get("OMNI_PKG_PARENT"):
        p = Path(os.environ["OMNI_PKG_PARENT"])
        return p
    here = Path(__file__).resolve().parent.parent  # 仓库 deploy_server/.. -> 仓库根
    tp = here / "third_party"
    if (tp / "omnizart").exists():
        return tp
    return here

_PKG_PARENT = _resolve_pkg_parent()
def _ckpt_dir(name: str = "music_piano-v2") -> Path:
    return _PKG_PARENT / "omnizart" / "checkpoints" / "music" / name

# ---- 惰性 TF 加载 (线程安全) -----------------------------------------
import fastapi, uvicorn  # noqa: E402  (前置依赖)
from fastapi import FastAPI, UploadFile, File, Form  # noqa: E402
import tempfile  # noqa: E402

app = FastAPI(title="Omnizart HTTP Engine", version="1.0.0")
_lock = threading.Lock()
_app_state = {"app": None, "model": "music_piano-v2", "device": "cpu", "error": ""}


def device_str() -> str:
    try:
        import tensorflow as tf
        return "gpu" if tf.config.list_physical_devices("GPU") else "cpu"
    except Exception:
        return "?"


def _ensure():
    with _lock:
        if _app_state["app"] is not None:
            return _app_state["app"], _app_state["error"], _app_state["model"]
        try:
            os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
            if str(_PKG_PARENT) not in sys.path:
                sys.path.insert(0, str(_PKG_PARENT))
            import tensorflow as tf  # noqa
            import tf_keras  # noqa
            tf.keras = tf_keras
            from omnizart.music.app import MusicTranscription  # noqa
            _app_state["app"] = MusicTranscription()
            _app_state["model"] = "music_piano-v2"
            _app_state["device"] = device_str()
            _app_state["error"] = ""
        except Exception as e:  # noqa: BLE001
            _app_state["app"] = None
            _app_state["error"] = f"{type(e).__name__}: {e}"
        return _app_state["app"], _app_state["error"], _app_state["model"]


@app.get("/health")
def health():
    _, err, model = _ensure()
    ok = _app_state["app"] is not None and not err
    return {
        "ok": ok,
        "available": ok,
        "model": model,
        "device": device_str() if ok else "?",
        "reason": "" if ok else (err or "加载失败"),
    }


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...), ckpt: str = Form("music_piano-v2")):
    engine, err, _ = _ensure()
    if engine is None:
        return fastapi.responses.JSONResponse(
            {"detail": f"Omnizart 不可用: {err}"}, status_code=503)
    cdir = _ckpt_dir(ckpt)
    if not (cdir / "saved_model.pb").exists():
        return fastapi.responses.JSONResponse(
            {"detail": f"checkpoint 不存在: {cdir}"}, status_code=400)
    # 存温 wav
    import soundfile as sf  # noqa
    suffix = os.path.splitext(file.filename or "in.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read()); tmpname = tmp.name
    # 若非 wav(如 mp3)解码转 wav
    wav = tmpname
    if suffix.lower() != ".wav":
        try:
            data, sr = sf.read(tmpname, dtype="float32")
            wav = tmpname + ".wav"
            sf.write(wav, data, sr, subtype="PCM_16")
        except Exception:
            wav = tmpname  # 交给解码方 libs
    out_dir = Path(tempfile.gettempdir()) / "omni_http_out"
    out_dir.mkdir(exist_ok=True)
    try:
        midi = engine.transcribe(wav, model_path=str(cdir), output=str(out_dir))
    finally:
        for p in (tmpname, wav if wav != tmpname else None):
            if p and Path(p).exists():
                try: Path(p).unlink()
                except Exception: pass
    events = []
    for inst in midi.instruments:
        for n in inst.notes:
            events.append({
                "start_s": round(float(n.start), 4),
                "dur_s": round(max(0.01, float(n.end) - float(n.start)), 4),
                "freq": round(440.0 * 2 ** ((int(n.pitch) - 69) / 12.0), 2),
                "midi": int(n.pitch),
                "velocity": int(n.velocity),
                "confidence": round(max(0.0, min(1.0, int(n.velocity) / 127.0)), 3),
            })
    events.sort(key=lambda e: e["start_s"])
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()
    print("Omnizart HTTP engine on http://%s:%d" % (a.host, a.port), flush=True)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
