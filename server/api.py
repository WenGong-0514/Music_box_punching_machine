"""HTTP API。单进程、单用户本地上位机, 状态全在内存 AppState。"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from . import engines
from .audio_io import decode_audio_file, make_waveform_peaks
from .gcode import (MachineParams, Z_KEYS, Z_LABELS, estimate, params_from, plan,
                    tape_to_gcode, validate_z, z_dict)
from .notetable import NoteTable
from .quantize import quantize_to_tape
from .state import SESSIONS_DIR, AppState, Session
from .tape import Tape

import soundfile as sf

DEFAULT_QUANTIZE = {
    "bpm": 120.0, "steps_per_beat": 8,
    "min_confidence": 0.05, "out_of_range": "fold", "min_gap_steps": 0,
    "octave_ghost_suppress": True,
    "auto_transpose": 24,      # ±24半音内自动找最优整曲移调(社区主流做法)
    "transpose_semitones": 0,  # 固定移调(正=升高), auto 开启时会被覆盖
    "shift_robust": True,      # 极高/极低点缀音(铃音等)不主导移调
    "max_midi": 127.0,         # 音域过滤上限(原始MIDI); 如 88=全丢音表以上铃音
    "min_midi": 0.0,
}
DEFAULT_ENGINE_PARAMS = {
    "basic_pitch": {"min_amplitude": 0.10},
    "dsp": {"onset_threshold": 0.5, "max_polyphony": 3,
            "min_freq": 65.0, "max_freq": 2500.0},
}


def make_router(state: AppState) -> APIRouter:
    router = APIRouter()

    # ---------------- 元信息 ----------------
    @router.get("/meta")
    def meta():
        return {
            "app": {"name": "MusicBox Tape Studio", "version": "0.1.0"},
            "engines": engines.available_engines(),
            "table": state.table.to_dict() if state.table else None,
            "defaults": {"quantize": DEFAULT_QUANTIZE,
                         "engine_params": DEFAULT_ENGINE_PARAMS},
            # 打孔 Z 三层(生成 G-code 前可选; 说明见 /api/gcode/params)
            "gcode_z": z_dict(params_from(state.z_params)),
            "gcode_supported": True,
        }

    # ---------------- 引擎动态配置(如 Omnizart HTTP 服务) ----------------
    @router.get("/engines")
    def list_engines():
        """刷新后返回可用性列表, 每个含 available/reason(供 GUI 置灰+解释)。"""
        return {"engines": engines.available_engines()}

    @router.get("/engines/omnizart")
    def omnizart_status():
        from .engines import remote_omnizart
        return remote_omnizart.status()

    @router.post("/engines/omnizart/config")
    def omnizart_config(body: dict):
        """body: {url?:str} 会话内切换到给定服务地址并重新探测。"""
        from .engines import remote_omnizart
        url = body.get("url")
        remote_omnizart.set_service_url(url)
        st = remote_omnizart.status()
        return {"engine": "omnizart", "configured_url": st.get("service_url"),
                "available": st.get("available"), "reason": st.get("reason"),
                "device": st.get("device"), "model": st.get("model")}

    # ---------------- 导入音频 (raw body, 不用 multipart) ----------------
    @router.post("/audio")
    async def import_audio(request: Request):
        raw = await request.body()
        if not raw:
            raise HTTPException(400, "空文件")
        fname = request.headers.get("x-file-name", "audio")
        fname = Path(fname).name
        ext = Path(fname).suffix.lower() or ".wav"
        sid = uuid.uuid4().hex[:12]
        sess_dir = SESSIONS_DIR / sid
        sess_dir.mkdir(parents=True, exist_ok=True)
        src_path = sess_dir / ("src" + ext)
        src_path.write_bytes(raw)
        try:
            x, sr = decode_audio_file(src_path)
        except Exception as e:
            raise HTTPException(422, f"音频解码失败: {e}")
        # 缓存单声道 wav(引擎统一输入)
        wav_path = sess_dir / "mono.wav"
        sf.write(str(wav_path), x, sr, subtype="PCM_16")
        sess = Session(id=sid, file_name=fname, wav_path=str(wav_path),
                       sr=sr, duration_s=float(len(x) / sr),
                       peaks=make_waveform_peaks(x, sr),
                       source_format=ext.lstrip("."))
        state.session = sess
        state.save_project()
        return sess.to_dict()

    # ---------------- 识别 ----------------
    @router.post("/transcribe")
    def transcribe(body: dict):
        sess = state.session
        if sess is None or not sess.wav_path or not Path(sess.wav_path).exists():
            raise HTTPException(400, "请先导入音频")
        engine_id = body.get("engine", "basic_pitch")
        avail = {e["id"] for e in engines.available_engines() if e["available"]}
        if engine_id not in avail:
            raise HTTPException(400, f"引擎 {engine_id} 不可用(可选项: {sorted(avail)})")
        params = {**DEFAULT_ENGINE_PARAMS.get(engine_id, {}),
                  **body.get("params", {})}
        job = state.jobs.create("transcribe")
        wav = sess.wav_path

        def run():
            try:
                cb = state.jobs.progress_cb(job)
                events = engines.transcribe_with(engine_id, wav, params, cb)
                sess.notes = events
                sess.notes_engine = engine_id
                sess.notes_params = params
                state.jobs.update(job, progress=1.0, status="done",
                                  message=f"{len(events)} 个音符",
                                  result={"count": len(events)})
                state.save_project()
            except Exception as e:
                state.jobs.update(job, status="error", error=f"{e.__class__.__name__}: {e}")

        threading.Thread(target=run, daemon=True).start()
        return {"job_id": job.id}

    @router.get("/jobs/{job_id}")
    def job(job_id: str):
        j = state.jobs.get(job_id)
        if j is None:
            raise HTTPException(404, "任务不存在")
        return j.to_dict()

    # ---------------- 载入外部识别结果(tools 高级引擎产物) ----------------
    @router.post("/notes")
    def import_notes(body: dict):
        events = body.get("events")
        if not isinstance(events, list) or not events:
            raise HTTPException(400, "events 为空或格式错误")
        norm = []
        dur = 0.0
        for e in events:
            try:
                start = float(e.get("start_s", e.get("start", 0)))
                freq = float(e.get("freq", e.get("pitch_hz", 0)))
                d = float(e.get("dur_s", e.get("dur", 0.2)))
                conf = float(e.get("confidence", e.get("velocity", 1.0)))
                if freq <= 0:
                    midi = e.get("midi")
                    if midi is None:
                        continue
                    freq = 440.0 * 2 ** ((float(midi) - 69) / 12.0)
                dur = max(dur, start + d)
                norm.append({"start_s": round(start, 4), "dur_s": round(max(0.01, d), 4),
                             "freq": round(freq, 2),
                             "confidence": round(max(0.0, min(1.0, conf)), 4)})
            except Exception:
                continue
        if not norm:
            raise HTTPException(422, "没有任何可用的音符事件")
        from .state import Session
        sess = state.session or Session()
        sess.notes = norm
        sess.notes_engine = str(body.get("engine", "external"))
        sess.duration_s = round(dur, 3)
        state.session = sess
        state.tape = None          # 旧纸带作废, 需重新量化
        state.save_project()
        return {"count": len(norm), "duration_s": round(dur, 3),
                "note": "已载入识别结果; 请在③里重新量化生成纸带"}

    # ---------------- MIDI 乐谱(选轨 -> 事件, 走③量化) ----------------
    @router.post("/midi")
    async def midi_analyze(request: Request):
        """上传 .mid → 解析轨清单(不落 notes)。"""
        raw = await request.body()
        if not raw:
            raise HTTPException(400, "空文件")
        fname = request.headers.get("x-file-name", "song.mid")
        fname = Path(fname).name
        if not fname.lower().endswith((".mid", ".midi", ".kar")):
            raise HTTPException(422, "仅支持 .mid/.midi")
        from . import midi_import
        from .state import SESSIONS_DIR
        sid = getattr(state, "_midi_id", None)
        import uuid as _uuid
        sid = _uuid.uuid4().hex[:12]
        sess_dir = SESSIONS_DIR / sid
        sess_dir.mkdir(parents=True, exist_ok=True)
        mid_path = sess_dir / fname
        mid_path.write_bytes(raw)
        state._midi_path = str(mid_path)
        try:
            return midi_import.analyze_midi(mid_path)
        except Exception as e:
            raise HTTPException(422, f"MIDI 解析失败: {e}")

    @router.post("/midi/select")
    def midi_select(body: dict):
        """body: {tracks:[idx,...]} → 把选中轨转事件存为 notes(engine=midi)。"""
        from . import midi_import
        from .state import Session
        mp = getattr(state, "_midi_path", None)
        if not mp or not Path(mp).exists():
            raise HTTPException(400, "请先上传 MIDI 文件(/api/midi)")
        sel = body.get("tracks") or []
        if not isinstance(sel, list) or not sel:
            raise HTTPException(422, "未选择任何乐器轨")
        events, dur = midi_import.selected_tracks_to_events(mp, [int(x) for x in sel])
        if not events:
            raise HTTPException(422, "所选轨道无可用音符(鼓/打击乐无音高一般不可用)")
        norm = []
        for e in events:
            norm.append({
                "start_s": round(float(e["start_s"]), 4),
                "dur_s": round(float(e["dur_s"]), 4),
                "freq": round(float(e["freq"]), 2),
                "confidence": round(float(e["confidence"]), 3),
                "midi": int(e["midi"]),
                "velocity": int(e.get("velocity", 96)),
                "program": int(e.get("program", 0)),
                "track": int(e.get("track", -1)),
            })
        sess = state.session or Session()
        sess.notes = norm
        sess.notes_engine = "midi:" + ",".join(str(int(x)) for x in sel)
        sess.duration_s = round(dur, 3)
        sess.source_format = "midi"
        sess.file_name = Path(mp).name
        state.session = sess
        state.tape = None          # 旧纸带作废
        state.save_project()
        return {"count": len(norm), "duration_s": round(dur, 3),
                "note": "已从 MIDI 选中轨道载入音符; 请在③里量化"}

    # ---------------- 量化编曲 ----------------
    @router.post("/quantize")
    def quantize(body: dict):
        sess = state.session
        if sess is None or not sess.notes:
            raise HTTPException(400, "请先完成音符识别")
        p = {**DEFAULT_QUANTIZE}
        p.update({k: v for k, v in body.items() if k in DEFAULT_QUANTIZE})
        tape, stats = quantize_to_tape(
            sess.notes, state.table,
            bpm=float(p["bpm"]), steps_per_beat=int(p["steps_per_beat"]),
            min_confidence=float(p["min_confidence"]),
            out_of_range=str(p["out_of_range"]),
            min_gap_steps=int(p["min_gap_steps"]),
            octave_ghost_suppress=bool(p["octave_ghost_suppress"]),
            transpose_semitones=int(p["transpose_semitones"]),
            auto_transpose=int(p["auto_transpose"]),
            shift_robust=bool(p.get("shift_robust", True)),
            max_midi=float(p.get("max_midi", 127.0)),
            min_midi=float(p.get("min_midi", 0.0)))
        state.tape = tape
        state.quantize_stats = stats
        state.save_project()
        return {"tape": tape.to_dict(), "stats": stats,
                "table": state.table.to_dict()}

    # ---------------- 纸带查看/编辑 ----------------
    @router.get("/tape")
    def get_tape():
        if state.tape is None:
            state.tape = Tape()
        return {"tape": state.tape.to_dict(), "table": state.table.to_dict(),
                "quantize_stats": state.quantize_stats}

    @router.post("/tape/edit")
    def tape_edit(body: dict):
        if state.tape is None:
            state.tape = Tape()
        tape = state.tape
        actions = body.get("actions", [])
        report = []
        for a in actions:
            op = a.get("op")
            try:
                if op == "toggle":
                    added = tape.toggle(int(a["row"]), int(a["col"]))
                    report.append({"op": op, "added": added})
                elif op == "remove_region":
                    n = tape.remove_region(int(a.get("row0", -1)), int(a.get("row1", 10 ** 9)),
                                           int(a.get("col0", -1)), int(a.get("col1", 99)))
                    report.append({"op": op, "removed": n})
                elif op == "clear":
                    tape.clear()
                    report.append({"op": op})
                elif op == "params":
                    tape.bpm = float(a.get("bpm", tape.bpm))
                    tape.steps_per_beat = int(a.get("steps_per_beat", tape.steps_per_beat))
                    report.append({"op": op})
                else:
                    report.append({"op": op, "error": "未知操作"})
            except Exception as e:
                report.append({"op": op, "error": str(e)})
        state.save_project()
        return {"tape": tape.to_dict(), "report": report}

    # ---------------- 导出 ----------------
    @router.get("/export/{fmt}")
    def export(fmt: str):
        if state.tape is None:
            raise HTTPException(400, "还没有纸带数据")
        sess = state.session
        base = Path(sess.file_name).stem if sess and sess.file_name else "tape"
        if fmt == "json":
            content = state.tape.to_json()
            media = "application/json"
            ext = "json"
        elif fmt == "csv":
            content = state.tape.to_csv()
            media = "text/csv"
            ext = "csv"
        elif fmt == "svg":
            content = state.tape.to_svg(state.table)
            media = "image/svg+xml"
            ext = "svg"
        elif fmt == "midi":
            from .midi_export import tape_to_midi_bytes
            content = tape_to_midi_bytes(state.tape, state.table)
            media = "audio/midi"
            ext = "mid"
        elif fmt == "gcode":
            content = tape_to_gcode(state.tape, state.table, params_from(state.z_params))
            media = "text/plain; charset=utf-8"
            ext = "gcode"
        else:
            raise HTTPException(404, f"未知格式 {fmt}")
        fn = f"{base}_tape.{ext}"
        return Response(content=content, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="{fn}"'})

    # ---------------- 音表(自定义) ----------------
    @router.post("/table")
    def set_table(body: dict):
        try:
            t = NoteTable(columns=list(body["columns"]),
                          base_octave=int(body.get("base_octave", 3)),
                          table_id="custom", name=body.get("name", "自定义音表"))
        except Exception as e:
            raise HTTPException(422, f"音表无效: {e}")
        state.table = t
        state.save_project()
        return {"table": t.to_dict(),
                "note": "音表已更新; 旧纸带孔位含义可能改变, 建议重新量化"}

    # ---------------- 工程快照 ----------------
    @router.get("/project")
    def project():
        sess = state.session
        return {
            "session": sess.to_dict() if sess else None,
            "notes_preview": (sess.notes[:200] if sess else []),
            "tape": state.tape.to_dict() if state.tape else None,
            "quantize_stats": state.quantize_stats,
            "table": state.table.to_dict() if state.table else None,
        }

    # ---------------- 打孔 Z 三层(生成 G-code 前由用户选定) ----------------
    def _apply_z(body: dict) -> None:
        """合并并校验三个 Z 高度; 不合法抛 422, 合法则写入 state 并存盘。"""
        cur = z_dict(params_from(state.z_params))
        for k in Z_KEYS:
            if body.get(k) is not None:
                cur[k] = body[k]
        err = validate_z(cur["z_work"], cur["z_safe"], cur["z_travel"])
        if err:
            raise HTTPException(422, err)
        state.z_params = {k: float(cur[k]) for k in Z_KEYS}
        state.save_project()

    @router.get("/gcode/params")
    def get_gcode_params():
        """GUI ⑤: 当前生效的三个 Z 高度 + 默认值 + 顺序规则(值越大越往下)。"""
        p = params_from(state.z_params)
        return {"current": z_dict(p), "defaults": z_dict(MachineParams()),
                "labels": Z_LABELS, "min": 0.0, "max": 200.0,
                "stroke_mm": p.z_stroke_mm,
                "rule": "Z 值越大越往下, 必须 移动高度 ≤ 安全高度 ≤ 工作高度"}

    @router.post("/gcode/params")
    def set_gcode_params(body: dict):
        """body: {z_work, z_safe, z_travel} —— 记入工程(重启后保留)。"""
        _apply_z(body)
        p = params_from(state.z_params)
        return {"current": z_dict(p), "stroke_mm": p.z_stroke_mm,
                "note": "已应用: 之后生成/下载的 G-code 都用这三个高度"}

    # ---------------- G-code(打孔) ----------------
    @router.post("/gcode")
    def gcode(body: dict | None = None):
        """生成打孔 G-code 并返回统计 + 预览(完整文本也在此返回)。

        body 里若带 z_work/z_safe/z_travel 会先应用(并记入工程), 便于"所见即所得"。
        """
        if state.tape is None or state.tape.hole_count() == 0:
            raise HTTPException(400, "还没有纸带数据")
        if body:
            _apply_z(body)
        p = params_from(state.z_params)
        planned = plan(state.tape, p)
        est = estimate(planned)
        text = tape_to_gcode(state.tape, state.table, p)
        lines = text.splitlines()
        return {"stats": est, "z": z_dict(p), "lines": len(lines), "bytes": len(text),
                "preview": "\n".join(lines[:40]), "gcode": text}

    return router
