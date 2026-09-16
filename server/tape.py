"""纸带数据模型。

物理原理: 纸带八音盒靠"孔经过读孔针/音齿"发声 —— 每个孔 = 一次拨弦,
音长靠孔之间的间隔(节奏留白)表达, 孔本身不表音长。
因此纸带数据 = 稀疏网格上的"孔集合": 行 row = 沿纸带的时间步(1格=1个可打孔位置),
列 col = 0..29 打孔列(音位)。同一行多列 = 和弦。

导出给打孔机时: 每个 (row, col) 对应一次打孔; row 间距 = 纸带推进一个步距。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


def step_seconds(bpm: float, steps_per_beat: int) -> float:
    """一个时间步(一格)对应的秒数。"""
    return 60.0 / (bpm * max(1, steps_per_beat))


def seconds_to_step(t: float, bpm: float, steps_per_beat: int) -> int:
    return int(round(t / step_seconds(bpm, steps_per_beat)))


@dataclass
class Tape:
    """一张纸带的孔集合。holes: [{"row": int, "col": int}], 建议按 row 升序。"""
    holes: list[dict] = field(default_factory=list)
    bpm: float = 120.0
    steps_per_beat: int = 8          # 每拍格子数(8 => 32分音符级分辨率)
    table_id: str = "30note_standard"
    meta: dict = field(default_factory=dict)   # 来源/说明等

    # ---- 基本操作 ----
    def sort(self) -> None:
        self.holes.sort(key=lambda h: (h["row"], h["col"]))

    def dedupe(self) -> int:
        """去掉完全重复的孔, 返回删除数。"""
        before = len(self.holes)
        self.sort()
        out: list[dict] = []
        prev: tuple | None = None
        for h in self.holes:
            key = (h["row"], h["col"])
            if key != prev:
                out.append(h)
                prev = key
        self.holes = out
        return before - len(out)

    def toggle(self, row: int, col: int) -> bool:
        """点击添加/删除一个孔。返回添加(True)或删除(False)。"""
        for h in self.holes:
            if h["row"] == row and h["col"] == col:
                self.holes.remove(h)
                return False
        self.holes.append({"row": int(row), "col": int(col)})
        self.sort()
        return True

    def remove_region(self, row0: int, row1: int, col0: int, col1: int) -> int:
        before = len(self.holes)
        self.holes = [h for h in self.holes
                      if not (row0 <= h["row"] <= row1 and col0 <= h["col"] <= col1)]
        return before - len(self.holes)

    def clear(self) -> None:
        self.holes = []

    # ---- 统计 ----
    def max_row(self) -> int:
        return max((h["row"] for h in self.holes), default=-1)

    def hole_count(self) -> int:
        return len(self.holes)

    def col_usage(self, ncols: int = 30) -> list[int]:
        usage = [0] * ncols
        for h in self.holes:
            if 0 <= h["col"] < ncols:
                usage[h["col"]] += 1
        return usage

    def duration_seconds(self) -> float:
        return (self.max_row() + 1) * step_seconds(self.bpm, self.steps_per_beat)

    def notes_playing(self, row: int) -> list[int]:
        return [h["col"] for h in self.holes if h["row"] == row]

    # ---- 机器参数(仅存档/溯源, 不参与计算; 权威值见 server/gcode.py MachineParams) ----
    # 注意: mm_per_step 实际 = 每步秒数 × feed_mm_s(随 bpm/每拍格数变化), 下面只是名义值。
    MACHINE_DEFAULTS = {
        "mm_per_step": 2.0,        # 名义值; 实际值见 gcode.plan() 返回的 mm_per_step
        "feed_mm_s": 16.0,         # 纸带孔距换算速度(mm/s): 决定音长/音梳复位时间
        "paper_width_mm": 70.0,    # 纸带宽
        "col_pitch_mm": 1.982759,  # 相邻打孔列间距 = 57.5/29
        "hole_diameter_mm": 2.0,   # 孔直径
    }

    # ---- 序列化 ----
    def to_dict(self) -> dict:
        self.sort()
        return {
            "format": "musicbox_tape_v1",
            "table_id": self.table_id,
            "bpm": self.bpm,
            "steps_per_beat": self.steps_per_beat,
            "step_seconds": round(step_seconds(self.bpm, self.steps_per_beat), 6),
            "ncols": 30,
            "rows": self.max_row() + 1,
            "hole_count": len(self.holes),
            "duration_seconds": round(self.duration_seconds(), 3),
            "holes": self.holes,
            "machine": dict(self.MACHINE_DEFAULTS),
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Tape":
        t = cls(holes=list(d.get("holes", [])),
                bpm=float(d.get("bpm", 120)),
                steps_per_beat=int(d.get("steps_per_beat", 8)),
                table_id=d.get("table_id", "30note_standard"),
                meta=dict(d.get("meta", {})))
        t.dedupe()
        return t

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=1)

    def to_csv(self) -> str:
        """CSV: 每行一个孔 row,col; 首行表头带参数。"""
        lines = [f"# bpm={self.bpm},steps_per_beat={self.steps_per_beat},table={self.table_id}",
                 "row,col"]
        for h in self.holes:
            lines.append(f"{h['row']},{h['col']}")
        return "\n".join(lines)

    def to_svg(self, table=None, cell_px: float = 12.0, label_w_px: int = 46) -> str:
        """纸带俯视示意图 SVG(便于预览/打印)。table 提供列音名标签。"""
        ncols = 30
        rows = max(self.max_row() + 1, 1)
        w = label_w_px + ncols * cell_px + 8
        h = rows * cell_px + 30
        names = [c.name if table else str(i) for i, c in
                 enumerate(table.columns)] if table else [str(i) for i in range(ncols)]
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
               f'viewBox="0 0 {w} {h}" font-family="Consolas,monospace">',
               f'<rect width="{w}" height="{h}" fill="#222"/>',
               f'<text x="{4}" y="{16}" fill="#eee" font-size="11">row {rows} × {ncols} col  (bpm {self.bpm:g}, {self.steps_per_beat}/beat)</text>']
        # 横向分隔线(每拍)
        beat_rows = max(1, int(round(self.steps_per_beat)))
        for r in range(rows + 1):
            y = 24 + r * cell_px
            major = (r % beat_rows == 0)
            svg.append(f'<line x1="{label_w_px}" y1="{y:.1f}" x2="{w - 4}" y2="{y:.1f}" '
                       f'stroke="{(255, 170, 0) if major else (120, 120, 120)}" stroke-width="{(2 if major else 0.6)}"/>')
        holeset = {(h["row"], h["col"]) for h in self.holes}
        for (row, col) in holeset:
            cx = label_w_px + (col + 0.5) * cell_px
            cy = 24 + (row + 0.5) * cell_px
            svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{cell_px * 0.33:.1f}" fill="#fff"/>')
        for col in range(ncols):
            svg.append(f'<text x="{label_w_px + (col + 0.5) * cell_px:.1f}" y="{h - 6}" '
                       f'fill="#eee" font-size="9" text-anchor="middle">{names[col]}</text>')
        svg.append("</svg>")
        return "\n".join(svg)
