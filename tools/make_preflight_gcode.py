"""预校验 G-code 生成器(参数直接取 server/gcode.py 的 MachineParams)。

机器模型:
  X = 纸带横向(音调), X+ 向右; X0 = 纸带左边缘线(冲针圆心, 无半径补偿)
  Y = 纸带纵向(时间), Y+ 向前
  Z = 冲针(值越大越往下): 移动高度 = 完全不冲孔时(G00 首尾/尾部外送带)
                            安全高度 = 冲孔后抬起位; 打孔阶段所有移动都在此
                            工作高度 = 冲孔位
      => 单次冲孔 Z 行程 = 安全高度 <-> 工作高度
  纸带 70mm 宽, 有效音频区 57.5mm, 左右空白各 6.25mm
  列分布 edge: X(col) = 6.25 + col*(57.5/29)  -> col0=6.25, col29=63.75
  结束: 不回 Y0, 继续向前 50mm 便于剪带

参数不在这里硬编码: 机械常量取 MachineParams, 三个 Z 高度取工程里 GUI ⑤ 选定的值
(doc["z_params"]), 免得跟真正的打孔 G-code 参数漂移。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTDIR = ROOT / 'out'

from server.gcode import params_from   # noqa: E402  (要先补好 sys.path)

doc = json.loads((ROOT / 'data' / 'project.json').read_text(encoding='utf-8'))
# 与 GUI ⑤ 里选定的三个 Z 高度保持一致(没选过就用 MachineParams 默认)
_P = params_from(doc.get('z_params'))

PAPER_W = _P.paper_width_mm
AUDIO_W = _P.audio_width_mm
MARGIN = _P.margin_mm                  # 6.25
NCOL = _P.ncol
FEED_MM_S = _P.feed_mm_s               # 纸带孔距换算 mm/s(几何, 决定音长)
Z_TRAVEL = _P.z_travel                 # 移动高度(G00 首尾/尾部外送带)
Z_SAFE = _P.z_safe                     # 安全高度(冲孔后抬起; 打孔阶段移动都在此)
Z_WORK = _P.z_work                     # 工作高度(冲孔)
Z_FEED = _P.z_feed                     # mm/min
DWELL = _P.dwell_s                     # s
XY_FEED = _P.xy_feed                   # mm/min
Y_FEED = _P.y_feed_mm_min              # mm/min, 打孔送带 F(只影响打孔耗时)
Y_TAIL = _P.y_tail_mm                  # 结束后继续前进 mm

tape = doc['tape']
if not tape:
    raise SystemExit('工程里还没有纸带(data/project.json 的 tape 为空)。\n'
                     '先在 GUI ③ 量化生成纸带, 再跑本工具。')
holes = tape['holes']
bpm = float(tape['bpm'])
spb = int(tape['steps_per_beat'])
step_seconds = 60.0 / (bpm * spb)
mm_per_step = step_seconds * FEED_MM_S


def x_of_col(col: float) -> float:
    return MARGIN + col * (AUDIO_W / (NCOL - 1))


def y_of_row(row: float) -> float:
    return row * mm_per_step


def f(v: float) -> str:
    s = '%.3f' % v
    return s.rstrip('0').rstrip('.') if '.' in s else s


HEADER = [
    '; 机器坐标:',
    ';   X = 纸带横向(音调), X+ = 向右;  X0 = 纸带左边缘线(冲针圆心, 无半径补偿)',
    ';   Y = 纸带纵向(时间),   Y+ = 纸带向前;  孔距换算 %.1f mm/s' % FEED_MM_S,
    ';   Z = 冲针(值越大越往下): %s = 移动高度(G00 首尾/尾部外送带), %s = 安全高度'
    '(冲孔后抬起; 打孔阶段移动都在此), %s = 工作高度(冲孔)'
    % (f(Z_TRAVEL), f(Z_SAFE), f(Z_WORK)),
    ';   => 单次冲孔 Z 行程 %.0f mm (安全高度 %s <-> 工作高度 %s)'
    % (abs(Z_WORK - Z_SAFE), f(Z_SAFE), f(Z_WORK)),
    '; 纸带: 宽 %.1fmm, 有效音频区 %.1fmm, 左右空白各 %.3fmm' % (PAPER_W, AUDIO_W, MARGIN),
    '; 列分布 edge: X(col) = %.3f + col * %.6f  (col0=%.3f, col29=%.3f)'
    % (MARGIN, AUDIO_W / (NCOL - 1), x_of_col(0), x_of_col(NCOL - 1)),
    '; Y 换算: %.1f mm/s x 时间; 本纸带 bpm=%g, %d格/拍 -> 每步 %.4f mm'
    % (FEED_MM_S, bpm, spb, mm_per_step),
    ';   八音盒上的节奏 = 孔距 ÷ 盒子走带速度, 与下面的送带 F 无关',
    '; 工艺: Z %.0f mm/min, 停留 %.2fs, X 空移 %.0f mm/min, 送带 F%.0f mm/min'
    % (Z_FEED, DWELL, XY_FEED, Y_FEED),
    '; 结束: 不回 Y0, 继续向前 %.0fmm 便于剪带' % Y_TAIL,
]


def punch(seq: list[str], x: float, y: float, label: str) -> None:
    seq.append('')
    seq.append('; --- %s: X=%.3f Y=%.3f ---' % (label, x, y))
    seq.append('G1 Y%s F%.0f' % (f(y), Y_FEED))
    seq.append('G0 X%s' % f(x))
    seq.append('G1 Z%s F%.0f' % (f(Z_WORK), Z_FEED))
    seq.append('G4 P%.3f' % DWELL)
    seq.append('G1 Z%s F%.0f' % (f(Z_SAFE), Z_FEED))
    seq.append(';   col %d' % int(round((x - MARGIN) / (AUDIO_W / (NCOL - 1)))))


def write(path: Path, title: str, body: list[str], end_y: float) -> None:
    lines = ['; ===== %s =====' % title]
    lines += HEADER
    lines += [';']
    lines += ['G21', 'G90', 'G94', '',
              '; --- 回移动高度与原点 ---', 'G0 Z%s' % f(Z_TRAVEL), 'G0 X0 Y0']
    if Z_SAFE != Z_TRAVEL:
        lines += ['; 降到安全高度: 打孔阶段(行内横移 + 换行送带)都在此高度',
                  'G0 Z%s' % f(Z_SAFE)]
    lines += body
    lines += ['', '; --- 结束: 抬到移动高度, 继续向前 %.0fmm 便于剪带(不回 Y0) ---' % Y_TAIL]
    if Z_TRAVEL != Z_SAFE:
        lines += ['G0 Z%s' % f(Z_TRAVEL)]
    lines += ['G1 Y%s F%.0f' % (f(end_y + Y_TAIL), Y_FEED), 'M30']
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


# ---- 文件1: 第一个音符 / 最后一个音符 ----
rows = sorted(holes, key=lambda h: (h['row'], h['col']))
fr = rows[0]['row']
lr = rows[-1]['row']
first = min((h for h in rows if h['row'] == fr), key=lambda h: h['col'])
lastset = [h for h in rows if h['row'] == lr]
last = max(lastset, key=lambda h: h['col'])
seq = ['; 孔1 = 时间上第一个音符: row=%d col=%d' % (first['row'], first['col']),
       '; 孔2 = 时间上最后一个音符: row=%d col=%d (该行共 %d 孔: %s)'
       % (last['row'], last['col'], len(lastset), sorted(h['col'] for h in lastset))]
punch(seq, x_of_col(first['col']), y_of_row(first['row']), '孔1 第一个音符')
punch(seq, x_of_col(last['col']), y_of_row(last['row']), '孔2 最后一个音符')
write(OUTDIR / 'canon_preflight_2holes.gcode', '打孔预校验: 第一个音符 / 最后一个音符',
      seq, y_of_row(last['row']))

# ---- 文件2: 左右边界 (col0 / col29) ----
seq2 = ['; 验证 X 两端行程与左右 6.25mm 留白; 两孔都在 Y=0 便于目视比对']
punch(seq2, x_of_col(0), 0.0, '左边界 col0')
punch(seq2, x_of_col(NCOL - 1), 0.0, '右边界 col29')
write(OUTDIR / 'canon_preflight_edges.gcode', 'X 边界校验: col0 / col29 (同一横线)', seq2, 0.0)
