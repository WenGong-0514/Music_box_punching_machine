"""预校验 G-code 生成器(按用户实测参数, 与 server/gcode.py 同一套语义)。

机器模型:
  X = 纸带横向(音调), X+ 向右; X0 = 纸带左边缘线(冲针圆心, 无半径补偿)
  Y = 纸带纵向(时间), Y+ 向前; 纸带恒速 8 mm/s
  Z = 冲针(值越大越往下): 0 = 最高位/快速移动, 6 = 安全高度(抬 4mm), 10 = 冲孔
      => 单次冲孔 Z 行程 4mm (6 <-> 10)
  纸带 70mm 宽, 有效音频区 57.5mm, 左右空白各 6.25mm
  列分布 edge: X(col) = 6.25 + col*(57.5/29)  -> col0=6.25, col29=63.75
  结束: 不回 Y0, 继续向前 50mm 便于剪带
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(r'D:\dsh_workspace\grbl_dev')
OUTDIR = ROOT / 'out'

PAPER_W = 70.0
AUDIO_W = 57.5
MARGIN = (PAPER_W - AUDIO_W) / 2.0     # 6.25
NCOL = 30
FEED_MM_S = 8.0                        # 纸带恒速 mm/s
Z_HOME = 0.0                           # 最高位/快速移动
Z_SAFE = 6.0                           # 安全高度
Z_WORK = 10.0                          # 冲孔位置
MOVE_Z = Z_SAFE                        # X/Y 空移时保持的高度
Z_FEED = 2000.0                        # mm/min
DWELL = 0.1                            # s
XY_FEED = 3000.0                       # mm/min
Y_FEED = 480.0                         # mm/min (= 8mm/s)
Y_TAIL = 50.0                          # 结束后继续前进 mm

doc = json.loads((ROOT / 'data' / 'project.json').read_text(encoding='utf-8'))
tape = doc['tape']
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
    ';   Y = 纸带纵向(时间),   Y+ = 纸带向前;  名义速度 %.1f mm/s' % FEED_MM_S,
    ';   Z = 冲针(值越大越往下): %s = 最高位/快速移动, %s = 安全高度(抬 %.0fmm), %s = 冲孔'
    % (f(Z_HOME), f(Z_SAFE), abs(Z_WORK - Z_SAFE), f(Z_WORK)),
    ';   => 单次冲孔 Z 行程 %.0f mm' % abs(Z_WORK - MOVE_Z),
    '; 纸带: 宽 %.1fmm, 有效音频区 %.1fmm, 左右空白各 %.3fmm' % (PAPER_W, AUDIO_W, MARGIN),
    '; 列分布 edge: X(col) = %.3f + col * %.6f  (col0=%.3f, col29=%.3f)'
    % (MARGIN, AUDIO_W / (NCOL - 1), x_of_col(0), x_of_col(NCOL - 1)),
    '; Y 换算: %.1f mm/s x 时间; 本纸带 bpm=%g, %d格/拍 -> 每步 %.4f mm'
    % (FEED_MM_S, bpm, spb, mm_per_step),
    '; 工艺: Z %.0f mm/min, 停留 %.2fs, X 空移 %.0f mm/min, 送带 %.0f mm/min'
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
    seq.append('G1 Z%s F%.0f' % (f(MOVE_Z), Z_FEED))
    seq.append(';   col %d' % int(round((x - MARGIN) / (AUDIO_W / (NCOL - 1)))))


def write(path: Path, title: str, body: list[str], end_y: float) -> None:
    lines = ['; ===== %s =====' % title]
    lines += HEADER
    lines += [';']
    lines += ['G21', 'G90', 'G94', '',
              '; --- 回最高位与原点 ---', 'G0 Z%s' % f(Z_HOME), 'G0 X0 Y0']
    if MOVE_Z != Z_HOME:
        lines += ['; 降到安全高度(之后 X/Y 移动都在此高度)', 'G0 Z%s' % f(MOVE_Z)]
    lines += body
    lines += ['', '; --- 结束: 继续向前 %.0fmm 便于剪带(不回 Y0) ---' % Y_TAIL,
              'G1 Y%s F%.0f' % (f(end_y + Y_TAIL), Y_FEED),
              'G0 Z%s' % f(Z_HOME), 'M30']
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
