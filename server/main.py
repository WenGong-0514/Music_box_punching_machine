"""FastAPI 入口: 启动本地上位机 Web 服务。

运行:  python -m server.main   (或 run.bat)
访问:  http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import re as _re
from dataclasses import fields as _dc_fields
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import make_router
from .notetable import NoteTable, load_note_table
from .state import SESSIONS_DIR, AppState, Session, ensure_dirs
from .tape import Tape

# Session 的字段名, 用来把 project.json 里的 session 字典安全地还原成 dataclass
_SESSION_FIELDS = {f.name for f in _dc_fields(Session)}

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"
DEFAULT_TABLE_FILE = DATA_DIR / "note_table_30note.json"

ensure_dirs()

state = AppState()

# ---- 启动恢复 ----
def _restore() -> None:
    doc = None
    pj = DATA_DIR / "project.json"
    if pj.exists():
        try:
            doc = json.loads(pj.read_text(encoding="utf-8"))
        except Exception:
            doc = None
    # 音表
    if doc and doc.get("table"):
        try:
            state.table = NoteTable.from_dict(doc["table"])
        except Exception:
            state.table = None
    if state.table is None:
        state.table = load_note_table(DEFAULT_TABLE_FILE)
    # 会话(音频/MIDI + 识别出的音符) —— 必须恢复:
    # 否则重启后 state.session 为 None, 前端 boot() 拿不到 note_count,
    # ③「量化 → 生成纸带」按钮会一直是灰的(纸带却还在, 看起来像 bug)。
    if doc and doc.get("session"):
        try:
            sess = Session(**{k: v for k, v in doc["session"].items()
                              if k in _SESSION_FIELDS})
            sess.notes = list(doc.get("notes") or [])
            # 老工程的文件名可能是 encodeURIComponent 过的(前端编码、旧后端没解码), 这里补一次
            if "%" in sess.file_name and _re.search(r"%[0-9A-Fa-f]{2}", sess.file_name):
                from urllib.parse import unquote
                sess.file_name = unquote(sess.file_name, errors="replace")
            # 解码缓存的 wav 若还在, 一并接回(重启后仍可直接重新识别)
            wav = SESSIONS_DIR / sess.id / "mono.wav"
            if wav.exists():
                sess.wav_path = str(wav)
            state.session = sess
        except Exception:
            state.session = None
    # 纸带(自包含, 可离线恢复)
    if doc and doc.get("tape"):
        try:
            state.tape = Tape.from_dict(doc["tape"])
        except Exception:
            state.tape = None
    state.quantize_stats = (doc or {}).get("quantize_stats", {})
    # 打孔 Z 三层(用户在 ⑤ 选过的值; 缺省时用 MachineParams 默认)
    state.z_params = dict((doc or {}).get("z_params") or {})


_restore()

app = FastAPI(title="MusicBox Tape Studio · 30音八音盒纸带上位机", version="0.1.0")
app.include_router(make_router(state), prefix="/api")


@app.get("/api/health")
def health():
    return {"ok": True, "table_loaded": state.table is not None}


class _NoCacheStatic(StaticFiles):
    """静态资源禁用浏览器缓存(本地单机上位机专用)。

    Starlette 默认只给 ETag/Last-Modified, 浏览器会按"启发式缓存"直接复用旧 js/css,
    连一次 304 询问都不发 —— 现象就是: index.html 是新的(界面多了控件),
    但 app.js 还是旧的(控件点了没反应、请求也发不出去)。
    web/ 会随开发频繁改动, 这里一律 no-store, 刷新即最新。
    """

    async def get_response(self, path: str, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp


if WEB_DIR.exists():
    app.mount("/", _NoCacheStatic(directory=str(WEB_DIR), html=True), name="web")


def main() -> None:
    import uvicorn
    print("=" * 56)
    print("  30音八音盒纸带打孔 · 电脑端上位机")
    print("  打开浏览器访问:  http://127.0.0.1:8765")
    print("=" * 56)
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
