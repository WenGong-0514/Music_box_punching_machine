"""抓取并解析 天天钢琴/PiaNoproblem 《夏野与暗恋（C调版）》的 Verovio SVG 谱面,
输出结构化钢琴谱参考数据 (tools/score_ref/xiaye_score.json)。

SVG 中每个 <g class="note" data-pname data-oct data-dur> 携带音高/八度/时值,
配合 x 坐标(按时值比例排版)可还原节拍位置。仅供个人学习对比评估。
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "score_ref"
BASE_URL = "https://i.insstudy.com/file/psm/sheetImg/20250701/a13ec5b5973b36ad69e7486a9c476e77"
NS = {"s": "http://www.w3.org/2000/svg"}
PC = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}


def download_pages(max_pages: int = 12) -> list[Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    got = []
    for i in range(1, max_pages + 1):
        url = f"{BASE_URL}/{i}.svg"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = r.read()
            if len(data) < 500 or b"<svg" not in data[:2000]:
                break
            p = OUT_DIR / f"page{i}.svg"
            p.write_bytes(data)
            got.append(p)
            print(f"  page{i}.svg  {len(data) / 1024:.0f}KB")
        except Exception:
            break
    return got


def parse_page(root: ET.Element, meas_offset: int, midi_out: list):
    """遍历一页。midi_out: 追加 (staff, onset_beats, dur_beats, midi, name, x, meas)。"""
    import itertools
    cnt = itertools.count(0)

    def x0_of_measure(m):
        # 该小节内第一条谱线 path 起点 x
        for staff in m.iter():
            if staff.tag == f"{{{NS['s']}}}g" and staff.get("class") == "staff":
                for path in staff.iter():
                    if path.tag == f"{{{NS['s']}}}path" and (path.get("d") or "").startswith("M"):
                        mm = re.match(r"M([\d.]+)", path.get("d"))
                        if mm:
                            return float(mm.group(1))
                break
        return None

    def iter_measures():
        for el in root.iter():
            if el.tag == f"{{{NS['s']}}}g" and el.get("class") == "measure":
                yield el

    for mi, meas in enumerate(iter_measures()):
        m_idx = meas_offset + mi
        x0 = x0_of_measure(meas)
        # 收集本小节内所有音符事件
        # note = g 元素, 可能有 data-pname(data-oct) 属性(独立音或和弦内层音)
        note_els = []
        for g in meas.iter():
            if g.tag == f"{{{NS['s']}}}g" and g.get("data-pname"):
                staff = None
                anc = g
                while anc is not None:
                    if anc.get("class") == "staff":
                        staff = int(anc.get("data-n"))
                        break
                    anc = _parent(root, anc)
                if staff is None:
                    # 回退: 依据谱线路径 y? 用 SVG y 对比两条谱线范围
                    staff = staff_from_y(g, root)
                note_els.append((staff, g))
        if not note_els:
            continue
        # x 坐标: 取该 g 内第一个音符符号 use 的 x
        events = []
        for staff, g in note_els:
            pname, octv = g.get("data-pname"), int(g.get("data-oct"))
            dur_raw = g.get("data-dur")
            x = glyph_x(g)
            if x is None:
                continue
            midi = 12 * (octv + 1) + PC[pname]
            name = pname.upper() + (("#" * 0)) + str(octv)
            events.append({"staff": staff, "x": x, "midi": midi, "name": name,
                           "pname": pname, "oct": octv, "dur_raw": dur_raw})
        if x0 is None:
            # 估计 x0 = min x
            x0 = min(e["x"] for e in events)
        # 同一 staff 内按 x 排序, 用 dur_raw 或间隔推节拍
        for staff in (1, 2):
            evs = sorted([e for e in events if e["staff"] == staff], key=lambda e: e["x"])
            if not evs:
                continue
            # 分组同一 onset(x 相同容差40)
            groups = []
            for e in evs:
                if groups and abs(e["x"] - groups[-1][0]) <= 40:
                    groups[-1][1].append(e)
                else:
                    groups.append((e["x"], [e]))
            # 累计节拍: 每组时值优先取组内 dur_raw 中位数; 否则取到下一组 x 间隔占
            # 四分音符间距的推断。已知排版近似线性: 推断比例用组内 dur 校验。
            # 先按 x 间距给各组打相对权重
            xs = [gx for gx, _ in groups]
            # 相对节拍比例: 假设间距与拍子线性, beat_px 从 dur 已知组反推
            durations = []  # (组下标, beats)
            for gi, (gx, members) in enumerate(groups):
                durs = [m["dur_raw"] for m in members if m["dur_raw"]]
                if durs:
                    d = durs[0]
                    # verovio: '2'=二分, '4'=四分, '8'=八分...
                    beats = 4 / int(d)
                    durations.append((gi, beats))
            # 从 dur 已知的点建立 beat_px(最小二乘)
            beat_px = None
            pairs = []
            for gi, b in durations:
                pairs.append((xs[gi] - x0, b))
            if len(pairs) >= 2:
                # 斜率 = beats / px 的平均
                slopes = [b / max(1e-6, px) for px, b in pairs]
                slopes = [s for s in slopes if 1e-4 < s < 1e-1]
                if slopes:
                    beat_px = 1.0 / (sum(slopes) / len(slopes))
            if beat_px is None and len(pairs) == 1:
                px, b = pairs[0]
                beat_px = px / b
            if beat_px is None:
                beat_px = (xs[-1] - xs[0]) / max(1.0, len(xs) - 1) * 2.0
            t = 0.0
            for gi, (gx, members) in enumerate(groups):
                onset = t
                # 组时值
                beats_here = None
                for gi2, b2 in durations:
                    if gi2 == gi:
                        beats_here = b2
                        break
                if beats_here is None:
                    if gi + 1 < len(groups):
                        beats_here = (groups[gi + 1][0] - gx) / beat_px
                    else:
                        beats_here = 4.0 / max(1, int(groups[gi][1][0].get("dur_raw") or 4))
                beats_here = max(0.25, min(8.0, beats_here))
                for m in members:
                    midi_out.append({
                        "staff": staff, "meas": m_idx + 1,
                        "onset": round(onset + (m_idx + 1 - 1) * 0, 4),
                        "onset_in_measure": round(onset, 4),
                        "beats": round(beats_here, 3),
                        "midi": m["midi"], "name": m["name"],
                    })
                t += beats_here


def _parent(root, el):
    for p in root.iter():
        for ch in p:
            if ch is el:
                return p
    return None


def staff_from_y(g, root):
    # 取该元素内 use 的 y, 与两谱线平均位置比较(谱线1(高音)在 y 更小/更大视方向)
    return None


def glyph_x(g):
    for u in g.iter():
        if u.tag == f"{{{NS['s']}}}use":
            try:
                return float(u.get("x"))
            except Exception:
                continue
    return None


def main() -> int:
    print("[1/2] 下载谱面 SVG …")
    pages = download_pages()
    print(f"      共 {len(pages)} 页")
    if not pages:
        print("      下载失败")
        return 2
    print("[2/2] 解析音符 …")
    all_notes = []
    meas_offset = 0
    for p in pages:
        try:
            tree = ET.parse(str(p))
        except Exception as e:
            print(f"      解析 {p.name} 失败: {e}")
            continue
        before = len(all_notes)
        parse_page(tree.getroot(), meas_offset, all_notes)
        n_new = len(all_notes) - before
        # 页内小节数估计(下次偏移)
        root = tree.getroot()
        nmeas = sum(1 for el in root.iter()
                    if el.tag == f"{{{NS['s']}}}g" and el.get("class") == "measure")
        meas_offset += nmeas
        print(f"      {p.name}: +{n_new} 音符, 小节数≈{nmeas}")
    out = {
        "title": "夏野与暗恋(C调版钢琴谱)",
        "composer": "闫东炜",
        "source": "PiaNoproblem/天天钢琴 SVG (Verovio)",
        "url": BASE_URL,
        "pages": len(pages),
        "notes": all_notes,
    }
    f = OUT_DIR / "xiaye_score.json"
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    rh = [n for n in all_notes if n["staff"] == 1]
    lh = [n for n in all_notes if n["staff"] == 2]
    print(f"      保存 {f}")
    print(f"      右手 {len(rh)} 音符, 左手 {len(lh)} 音符, 总 {len(all_notes)}")
    print("      样例(前12):")
    for n in all_notes[:12]:
        print("      ", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
