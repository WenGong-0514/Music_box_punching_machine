"""FastAPI 入口: 启动本地上位机 Web 服务。

运行:  python -m server.main   (或 run.bat)
访问:  http://127.0.0.1:8765
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import make_router
from .notetable import NoteTable, load_note_table
from .state import AppState, ensure_dirs
from .tape import Tape

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
    # 纸带(自包含, 可离线恢复)
    if doc and doc.get("tape"):
        try:
            state.tape = Tape.from_dict(doc["tape"])
        except Exception:
            state.tape = None
    state.quantize_stats = (doc or {}).get("quantize_stats", {})


_restore()

app = FastAPI(title="MusicBox Tape Studio · 30音八音盒纸带上位机", version="0.1.0")
app.include_router(make_router(state), prefix="/api")


@app.get("/api/health")
def health():
    return {"ok": True, "table_loaded": state.table is not None}


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def main() -> None:
    import uvicorn
    print("=" * 56)
    print("  30音八音盒纸带打孔 · 电脑端上位机")
    print("  打开浏览器访问:  http://127.0.0.1:8765")
    print("=" * 56)
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
