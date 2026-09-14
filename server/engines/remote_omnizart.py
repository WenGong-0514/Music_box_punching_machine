"""Omnizart via HTTP 引擎服务 (本机不再 import TensorFlow).

设计: Omnizart(music_piano-v2) 是不可靠在其本机 import TF 的 Keras2 模型,
为此改成"引擎服务"形态 —— 由一个能跑它的机器(Docker/服务器)常驻暴露 HTTP 端口,
本机 backend 只当它"可达"时才把该引擎列为可选, 并把 wav POST 给它换回 events。

端点约定 (见 deploy_server/SERVICE-INSTALL.md 如何去部署):
    GET  /health
        200 {"ok": true, "available": true, "model": "music_piano-v2", "device": "gpu/cpu", "reason": "..."}
        available=false 时给下载原因。
    POST /transcribe    (multipart: file=<wav>; form: ckpt=music_piano-v2)
        200 -> events 数组 (与 GUI /api/notes 兼容: start_s/dur_s/freq/...)

地址配置(优先级高->低):
    - 本机服务已在跑:            http://127.0.0.1:8766 (默认)
    - 远程服务器 Omnizart 服务: 环境变量 OMNIZART_SERVICE_URL=https://<ip>:<port>
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from urllib import request, error

DEFAULT_LOCAL = "http://127.0.0.1:8766"

_override_url = None

_cache = {"time": 0.0, "ok": None, "reason": "", "model": "", "device": ""}
_cache_lock = threading.Lock()
_LAST_TTL = 30.0  # 秒;健康探测短期缓存,以免每 GET /meta 都开连接


def set_service_url(url: str) -> None:
    """会话内覆盖服务地址(供 GUI 填写/测试用)。空则回到默认/环境变量。"""
    global _override_url, _cache
    with _cache_lock:
        _override_url = (url or "").strip() or None if url is not None else None
        _cache = {"time": 0.0, "ok": None, "reason": "", "model": "", "device": ""}


def configured_url() -> str:
    base = _override_url or os.environ.get("OMNIZART_SERVICE_URL") or DEFAULT_LOCAL
    return base.rstrip("/")


def _probe_now() -> dict:
    """对已配置服务做一次健康探测, 返回描述。异常不抛, 只把原因放进 reason。"""
    url = configured_url() + "/health"
    info = {"ok": False, "available": False, "reason": f"服务不可达({url})", "model": "", "device": ""}
    try:
        req = request.Request(url, method="GET", headers={"Accept": "application/json"})
        with request.urlopen(req, timeout=2.5) as r:  # noqa: S310 (127.0.0.1/内网)
            code = r.status
            raw = r.read().decode("utf-8", "replace")
        if code == 200:
            try:
                d = json.loads(raw)
            except Exception:
                d = {}
            info["ok"] = bool(d.get("ok", True))
            info["available"] = bool(d.get("available", False))
            info["model"] = str(d.get("model", ""))
            info["device"] = str(d.get("device", ""))
            info["reason"] = str(d.get("reason", "") or "")
            if not info["available"]:
                info["reason"] = info["reason"] or ("服务返回不可用:" + str(d))
        else:
            info["reason"] = f"服务非 200 (HTTP {code})"
        return info
    except error.URLError as e:
        info["reason"] = f"服务不可达({url}): {getattr(e, 'reason', e)}"
        return info
    except error.HTTPError as e:
        info["reason"] = f"服务 HTTP {e.code}"
        return info
    except Exception as e:  # noqa: BLE001
        info["reason"] = f"探测异常: {type(e).__name__}: {e}"
        return info


def probe(cached=True) -> dict:
    """返回 {ok, available, model, device, reason}。可用性以 available 为准。"""
    global _cache
    with _cache_lock:
        if cached and (time.time() - _cache["time"] < _LAST_TTL) and _cache["ok"] is not None:
            return dict(_cache)
        now = _probe_now()
        now["time"] = time.time()
        _cache = now
        return dict(_cache)


def available() -> bool:
    return bool(probe().get("available"))


def status() -> dict:
    """供 available_engines()/meta 使用: 返回引擎描述附加词。"""
    p = probe()
    desc = {
        "id": "omnizart",
        "name": "Omnizart(music_piano-v2; HTTP 服务)",
        "available": bool(p.get("available")),
        "kind": "service",
        "reason": p.get("reason") or ("" if p.get("available") else "未启用"),
        "service_url": configured_url(),
        "hint": "钢琴专用转录; 由 HTTP 引擎服务提供(本机不装 TensorFlow)",
    }
    if p.get("available"):
        device = p.get("device")
        model = p.get("model")
        desc["hint"] = f"{desc['hint']} device={device or '?'}; model={model or '-'}"
    else:
        desc["hint"] += "。未配置/不可达的服务无法选用。" + (f" 原因: {desc['reason']}")
    return desc


def transcribe(wav_path: str, params: dict, progress=None) -> list[dict]:
    """POST 到已配置的服务做转录。progress: 在此仅给阶段提示(服务无回流进度)。"""
    url = configured_url() + "/transcribe"
    if progress:
        progress(0.05, "连接 Omnizart 服务 …")
    p = probe(cached=False)
    if not p.get("available"):
        raise RuntimeError(f"Omnizart 服务不可用: {p.get('reason')}")
    if not Path(wav_path).exists():
        raise FileNotFoundError(wav_path)
    ckpt = str(params.get("model") or params.get("ckpt") or "music_piano-v2")
    # multipart 上传 wav
    boundary = "----omnizart-" + os.urandom(8).hex()
    body = bytearray()
    def field(name, value):
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    field("ckpt", ckpt)
    with open(wav_path, "rb") as f:
        audio = f.read()
    body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"in.wav\"\r\n"
                f"Content-Type: audio/wav\r\n\r\n".encode())
    body.extend(audio)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    if progress:
        progress(0.2, "服务端转录中(整曲可能数十秒~几分钟)…")
    req = request.Request(url, data=bytes(body), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with request.urlopen(req, timeout=3600) as r:  # noqa: S310
            raw = r.read()
    except error.HTTPError as e:
        why = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Omnizart 服务转录失败 HTTP {e.code}: {why[:300]}")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Omnizart 服务转录失败: {type(e).__name__}: {e}")
    try:
        events = json.loads(raw.decode("utf-8"))
    except Exception:
        raise RuntimeError(f"Omnizart 服务返回非 JSON({raw[:200]})")
    if not isinstance(events, list):
        raise RuntimeError(f"Omnizart 服务返回异常: {str(events)[:300]}")
    if progress:
        progress(1.0, f"完成: {len(events)} 个音符")
    return events
