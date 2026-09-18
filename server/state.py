"""单用户会话/任务管理 + 项目持久化。"""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
PROJECT_FILE = DATA_DIR / "project.json"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- Job
@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"      # queued|running|done|error
    progress: float = 0.0
    message: str = ""
    result: dict | None = None
    error: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status,
                "progress": round(self.progress, 3), "message": self.message,
                "result": self.result, "error": self.error}


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: str) -> Job:
        j = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[j.id] = j
        return j

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: Job, *, progress: float | None = None,
               message: str | None = None, status: str | None = None,
               result: dict | None = None, error: str | None = None) -> None:
        with self._lock:
            if progress is not None:
                job.progress = float(progress)
            if message is not None:
                job.message = message
            if status is not None:
                job.status = status
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error

    def progress_cb(self, job: Job):
        def cb(p: float, msg: str = "") -> None:
            self.update(job, progress=p, message=msg)
        return cb


# ---------------------------------------------------------------- Session
@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    file_name: str = ""
    wav_path: str = ""          # 解码后的单声道 wav 缓存(引擎输入)
    sr: int = 22050
    duration_s: float = 0.0
    peaks: list = field(default_factory=list)   # 波形包络
    source_format: str = ""
    notes: list = field(default_factory=list)   # 最近一次识别结果
    notes_engine: str = ""
    notes_params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "file_name": self.file_name, "sr": self.sr,
                "duration_s": round(self.duration_s, 3), "peaks": self.peaks,
                "source_format": self.source_format,
                "note_count": len(self.notes),
                "notes_engine": self.notes_engine}


class AppState:
    """内存中的当前工程状态(本地单用户足够)。"""

    def __init__(self) -> None:
        self.table = None          # NoteTable
        self.session: Session | None = None
        self.tape = None           # Tape (或 None)
        self.quantize_stats: dict = {}
        self.z_params: dict = {}   # 打孔 Z 三层高度(生成 G-code 前在 GUI 里选)
        self.jobs = JobManager()

    # ---- 持久化 ----
    def save_project(self) -> None:
        ensure_dirs()
        doc = {
            "table": self.table.to_dict() if self.table else None,
            "session": self.session.to_dict() if self.session else None,
            "notes": self.session.notes if self.session else [],
            "tape": self.tape.to_dict() if self.tape else None,
            "quantize_stats": self.quantize_stats,
            "z_params": self.z_params,
        }
        PROJECT_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                                encoding="utf-8")

    def load_project(self) -> None:
        if PROJECT_FILE.exists():
            try:
                doc = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
                return doc
            except Exception:
                return None
        return None
