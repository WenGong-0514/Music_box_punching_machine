"""纸带 -> 打孔 G-code 生成(GRBL)。

机器模型(按用户实测确认):
  X = 纸带横向(音调), X+ 向右;  X0 = 纸带左边缘线(冲针圆心, 无半径补偿)
  Y = 纸带纵向(时间),   Y+ 向前
  Z = 冲针(值越大越往下) —— 三层, 生成打孔前可在 GUI ⑤ 里选(见 /api/gcode/params):
      移动高度 = 0    完全不冲孔时用: G00 首尾定位、最后 50mm 外送带
      安全高度 = 4    冲孔后抬起位; 打孔阶段的所有移动(行内横移 + 换行送带)都在此高度
      工作高度 = 10   冲孔位(G1 压下)
  => 每次冲孔的实际 Z 行程 = 6mm (安全高度 4 <-> 工作高度 10)

  !! 两个"速度"是两件事, 不要混:
     feed_mm_s     纸带孔距换算(几何): mm_per_step = 每步秒数 * feed_mm_s
                   => 决定孔与孔的距离 = 八音盒上听起来多快 / 音梳有多少时间复位
     y_feed_mm_min 打孔机送带进给(G-code 里的 F): 只决定"打孔要打多久", 不影响音乐
     (八音盒上的实际节奏 = 孔距 ÷ 八音盒走带速度, 与 y_feed_mm_min 无关)
  纸带 70mm 宽, 有效音频区 57.5mm, 左右空白各 6.25mm
  列分布(edge): X(col) = 6.25 + col*(57.5/29) -> col0=6.25, col29=63.75
  结束时: 不回 Y0, 而是继续向前 y_tail_mm(默认 100mm)便于剪下纸带

路线规划:
  - 同一 row 的多孔 = 同一横线, 纸带停住, 按 X 依次冲完该行
  - 每行从离当前 X 最近的一端进入(少空移)
  - 空行跳过(只对有孔行定位)
  - 打孔阶段: 冲孔走 安全高度<->工作高度; 行内横移与换行送带都保持在安全高度
  - 完全不冲孔的部分(首尾定位、尾部外送带): 抬到移动高度走 G00
"""
from __future__ import annotations

from dataclasses import dataclass

from .tape import Tape


@dataclass
class MachineParams:
    paper_width_mm: float = 70.0
    audio_width_mm: float = 57.5
    ncol: int = 30
    col_mode: str = "edge"            # 'edge' = 首末列圆心贴有效区两端(用户已确认)
    feed_mm_s: float = 16.0           # 纸带孔距换算 mm/s(几何): 8 -> 16 = 孔距翻倍
                                      #   决定音长与音梳复位时间; 与打孔快慢无关
    z_work: float = 10.0              # 工作高度: 冲孔位(G1 压到这里)
    z_safe: float = 4.0               # 安全高度: 冲孔后抬起位; 打孔阶段所有移动都在此高度
    z_travel: float = 0.0             # 移动高度: 完全不冲孔时(G00 首尾/尾部外送带)的高度
    z_feed: float = 2000.0            # mm/min, Z 下压/抬起(用户实测上限)
    dwell_s: float = 0.1              # 冲孔停留
    xy_feed: float = 3000.0           # mm/min, X 空移
    y_feed_mm_min: float = 1000.0     # mm/min, 打孔机送带 F(用户 Y 轴实测值)
                                      #   只影响打孔耗时; 若 $111 允许也可提到 2000
    y_tail_mm: float = 100.0           # 结束后继续前进(便于剪带)
    include_header: bool = True

    @property
    def margin_mm(self) -> float:
        return (self.paper_width_mm - self.audio_width_mm) / 2.0

    @property
    def z_stroke_mm(self) -> float:
        """单次冲孔的 Z 行程(mm): 安全高度 <-> 工作高度。"""
        return abs(self.z_work - self.z_safe)

    # 兼容旧字段名(文档/工具/旧快照里出现过这两个名字)
    @property
    def z_home(self) -> float:
        return self.z_travel

    @property
    def move_z(self) -> float:
        return self.z_safe

    def x_of_col(self, col: int) -> float:
        if self.col_mode == "center":
            pitch = self.audio_width_mm / self.ncol
            return self.margin_mm + (col + 0.5) * pitch
        pitch = self.audio_width_mm / (self.ncol - 1)
        return self.margin_mm + col * pitch


Z_KEYS = ("z_work", "z_safe", "z_travel")
Z_LABELS = {"z_work": "工作高度", "z_safe": "安全高度", "z_travel": "移动高度"}


def validate_z(z_work: float, z_safe: float, z_travel: float) -> str | None:
    """校验三个 Z 高度。值越大越往下, 所以必须 移动 ≤ 安全 ≤ 工作。

    返回中文错误信息; 合法返回 None。
    """
    for k, v in (("z_work", z_work), ("z_safe", z_safe), ("z_travel", z_travel)):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return f"{Z_LABELS[k]}不是数字"
        if not (0.0 <= v <= 200.0):
            return f"{Z_LABELS[k]}应在 0~200mm 之间(当前 {v})"
    if not (float(z_travel) <= float(z_safe) <= float(z_work)):
        return (f"高度顺序不对: Z 值越大越往下, 必须 移动高度 ≤ 安全高度 ≤ 工作高度"
                f"(当前 移动 {z_travel} / 安全 {z_safe} / 工作 {z_work})")
    return None


def params_from(z: dict | None = None) -> MachineParams:
    """按界面选定的三个 Z 高度构造参数(其余保持机械常量)。z 里缺的项用默认值。"""
    p = MachineParams()
    for k in Z_KEYS:
        v = (z or {}).get(k)
        if v is not None:
            setattr(p, k, float(v))
    return p


def z_dict(p: MachineParams) -> dict:
    return {k: getattr(p, k) for k in Z_KEYS}


def fmt(v: float) -> str:
    s = "%.3f" % v
    return s.rstrip("0").rstrip(".") if "." in s else s


def plan(tape: Tape, params: MachineParams | None = None) -> dict:
    """按 row 分组 -> [{row, y, cols:[(col,x)...]}]; 每行从最近端进入。"""
    p = params or MachineParams()
    step_s = 60.0 / (max(1.0, float(tape.bpm)) * max(1, int(tape.steps_per_beat)))
    rows: dict[int, set[int]] = {}
    for h in tape.holes:
        rows.setdefault(int(h["row"]), set()).add(int(h["col"]))
    seq = []
    x_ref = 0.0
    for row in sorted(rows):
        cols = sorted(rows[row], key=lambda c: p.x_of_col(c))
        if len(cols) > 1 and abs(p.x_of_col(cols[-1]) - x_ref) < abs(p.x_of_col(cols[0]) - x_ref):
            cols = list(reversed(cols))
        seq.append({"row": row, "y": row * step_s * p.feed_mm_s,
                    "cols": [(c, p.x_of_col(c)) for c in cols]})
        x_ref = p.x_of_col(cols[-1])
    return {"plan": seq, "step_seconds": step_s,
            "mm_per_step": step_s * p.feed_mm_s, "params": p}


def estimate(planned: dict) -> dict:
    """粗估总时长(秒): 送带 + X 空移 + Z 冲孔行程 + 停留 + 尾部前进。"""
    p: MachineParams = planned["params"]
    seq = planned["plan"]
    t = 0.0
    y_prev = 0.0
    x_prev = 0.0
    holes = 0
    t_z = 0.0
    t_dwell = 0.0
    t_y = 0.0
    t_x = 0.0
    for item in seq:
        dy = abs(item["y"] - y_prev)
        t_y += dy / p.y_feed_mm_min * 60.0
        t += dy / p.y_feed_mm_min * 60.0
        y_prev = item["y"]
        for _c, x in item["cols"]:
            dx = abs(x - x_prev)
            t_x += dx / p.xy_feed * 60.0
            t += dx / p.xy_feed * 60.0
            x_prev = x
            zt = p.z_stroke_mm * 2 / p.z_feed * 60.0        # 下 + 抬
            t_z += zt
            t += zt
            t_dwell += p.dwell_s
            t += p.dwell_s
            holes += 1
    tail = p.y_tail_mm / p.y_feed_mm_min * 60.0
    t_y += tail
    t += tail
    return {"holes": holes, "rows_with_holes": len(seq),
            "total_seconds": round(t, 1), "total_minutes": round(t / 60.0, 1),
            "tape_len_mm": round(y_prev + p.y_tail_mm, 1),
            "punch_len_mm": round(y_prev, 1),
            "z_stroke_mm": p.z_stroke_mm,
            "breakdown_s": {"送带": round(t_y, 1), "X空移": round(t_x, 1),
                            "Z冲程": round(t_z, 1), "停留": round(t_dwell, 1)}}


def tape_to_gcode(tape: Tape, table=None, params: MachineParams | None = None) -> str:
    p = params or MachineParams()
    planned = plan(tape, p)
    seq = planned["plan"]
    est = estimate(planned)

    L: list[str] = []
    A = L.append
    if p.include_header:
        A("; ===== 30音八音盒纸带打孔 G-code (GRBL) =====")
        A("; 生成自: 纸带 %d 孔 / %d 行, bpm=%s, 每拍 %s 格"
          % (tape.hole_count(), tape.max_row() + 1, tape.bpm, tape.steps_per_beat))
        A(";")
        A("; 机器坐标:")
        A(";   X = 纸带横向(音调), X+ = 向右;  X0 = 纸带左边缘线(冲针圆心, 无半径补偿)")
        A(";   Y = 纸带纵向(时间),   Y+ = 纸带向前;  孔距换算 %.1f mm/s (每步 %.4f mm)"
          % (p.feed_mm_s, planned["mm_per_step"]))
        A(";       !! 八音盒上的节奏 = 孔距 ÷ 盒子走带速度; 下面的送带 F 只决定打孔耗时, 不影响音乐")
        A(";   Z = 冲针(值越大越往下): %s = 移动高度(G00 首尾/尾部外送带), %s = 安全高度"
          "(冲孔后抬起; 打孔阶段所有移动都在此), %s = 工作高度(冲孔)"
          % (fmt(p.z_travel), fmt(p.z_safe), fmt(p.z_work)))
        A(";   => 单次冲孔 Z 行程 = %.0f mm (安全高度 %s <-> 工作高度 %s)"
          % (p.z_stroke_mm, fmt(p.z_safe), fmt(p.z_work)))
        A("; 纸带 %.1fmm 宽, 有效音频区 %.1fmm, 左右空白各 %.3fmm"
          % (p.paper_width_mm, p.audio_width_mm, p.margin_mm))
        if p.col_mode == "edge":
            A("; 列分布 edge: X(col) = %.3f + col * %.6f (col0=%.3f, col%d=%.3f)"
              % (p.margin_mm, p.audio_width_mm / (p.ncol - 1), p.x_of_col(0),
                 p.ncol - 1, p.x_of_col(p.ncol - 1)))
        else:
            A("; 列分布 center: X(col) = %.3f + (col+0.5) * %.6f"
              % (p.margin_mm, p.audio_width_mm / p.ncol))
        A("; 时间: 每步 %.6f s -> 每步 %.4f mm (Y = row * 每步 mm)"
          % (planned["step_seconds"], planned["mm_per_step"]))
        A(";")
        A("; 路线: 同拍多孔=停带按 X 依次冲; 每行从最近端进入; 空行跳过")
        A(";       打孔阶段(行内横移 + 换行送带)保持在 Z%s(安全高度); 冲孔走 %s <-> %s"
          % (fmt(p.z_safe), fmt(p.z_safe), fmt(p.z_work)))
        A(";       完全不冲孔的部分(首尾定位 + 尾部外送带)在 Z%s(移动高度)" % fmt(p.z_travel))
        A("; 结束: 不回 Y0; 抬到移动高度后继续向前 %.0fmm 便于剪带" % p.y_tail_mm)
        A(";")
        A("; Z 速度 %.0f mm/min; 停留 %.2fs; X 空移 %.0f mm/min; 送带 F%.0f mm/min"
          % (p.z_feed, p.dwell_s, p.xy_feed, p.y_feed_mm_min))
        A(";   (送带 F 只影响打孔耗时; 孔距/音乐节奏由上面的 %.1f mm/s 决定)" % p.feed_mm_s)
        A("; 预估: %d 孔 / %d 个有孔行 / 冲孔段纸带 %.1f mm / 全过程约 %.1f 分钟"
          % (est["holes"], est["rows_with_holes"], est["punch_len_mm"], est["total_minutes"]))
        A(";   分解: 送带 %.0fs | X空移 %.0fs | Z冲程 %.0fs | 停留 %.0fs"
          % (est["breakdown_s"]["送带"], est["breakdown_s"]["X空移"],
             est["breakdown_s"]["Z冲程"], est["breakdown_s"]["停留"]))
        A(";   (Z 实际速度受 GRBL $112 最大速率 与 $122 加速度限制; 达不到会自动限速, 不影响孔位)")
        A(";")
    A("G21")
    A("G90")
    A("G94")
    A("")
    A("; --- 回移动高度与原点 ---")
    A("G0 Z%s" % fmt(p.z_travel))
    A("G0 X0 Y0")
    if p.z_safe != p.z_travel:
        A("; 降到安全高度: 打孔阶段(行内横移 + 换行送带)都在此高度")
        A("G0 Z%s" % fmt(p.z_safe))

    for item in seq:
        A("")
        A("; --- row %d : Y=%.3f (%d 孔) ---" % (item["row"], item["y"], len(item["cols"])))
        A("G1 Y%s F%.0f" % (fmt(item["y"]), p.y_feed_mm_min))
        for col, x in item["cols"]:
            A("G0 X%s" % fmt(x))
            A("G1 Z%s F%.0f" % (fmt(p.z_work), p.z_feed))
            A("G4 P%.3f" % p.dwell_s)
            A("G1 Z%s F%.0f" % (fmt(p.z_safe), p.z_feed))
            A(";   col %d" % col)

    A("")
    A("; --- 结束: 抬到移动高度, 继续向前 %.0fmm 便于剪带(不回 Y0) ---" % p.y_tail_mm)
    if p.z_travel != p.z_safe:
        A("G0 Z%s" % fmt(p.z_travel))
    A("G1 Y%s F%.0f" % (fmt(seq[-1]["y"] + p.y_tail_mm if seq else p.y_tail_mm),
                        p.y_feed_mm_min))
    A("M30")
    return "\n".join(L) + "\n"
