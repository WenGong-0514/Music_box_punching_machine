// 纸带网格视图: 渲染 + 交互(点选/擦除/缩放/播放头)
export class TapeView {
  constructor(canvas, wrap) {
    this.cv = canvas; this.ctx = canvas.getContext('2d'); this.wrap = wrap;
    this.cell = 13;            // px per step (zoom)
    this.labelW = 66;
    this.rulerH = 24;
    this.holes = [];           // [{row,col}]
    this.names = [];           // 30 note names, index=col (自底向上展示?)
    this.bpm = 120; this.spb = 8;
    this.playheadRow = -1;
    this._bind();
  }

  get ncols() { return 30; }
  get stepS() { return 60 / (this.bpm * Math.max(1, this.spb)); }
  get rows() { return this.holes.reduce((m, h) => Math.max(m, h.row), -1) + 1; }
  get colOrder() { return this.names.map((_, i) => i); }  // 展示顺序: col0 在上方

  // ---- 数据 ----
  setTape(tape) {
    this.holes = (tape.holes || []).slice();
    this.bpm = tape.bpm || 120; this.spb = tape.steps_per_beat || 8;
    this.cell = Math.min(this.cell, this.maxCell());
    this.layout(); this.draw();
  }
  // 防止 canvas 超宽(浏览器上限), 长纸带自动压小格子
  maxCell() {
    const rows = Math.max(this.rows, 1);
    return Math.max(3, Math.floor(26000 / rows));
  }
  setTable(notes) { this.names = notes.map(n => n.name); }

  // ---- 几何 ----
  layout() {
    const rows = Math.max(this.rows, 1);
    this.cv.width = Math.max(320, Math.ceil(this.labelW + rows * this.cell + 8));
    this.cv.height = this.rulerH + this.ncols * this.cell + 14;
    this.cv.style.width = this.cv.width + 'px';
    this.cv.style.height = this.cv.height + 'px';
  }
  rowToX(row) { return this.labelW + row * this.cell + this.cell / 2; }
  colToY(col) { return this.rulerH + col * this.cell + this.cell / 2; }
  xToRow(x) { return Math.floor((x - this.labelW) / this.cell); }
  yToCol(y) { return Math.floor((y - this.rulerH) / this.cell); }

  // ---- 绘制 ----
  draw() {
    const ctx = this.ctx, W = this.cv.width, H = this.cv.height;
    const ncols = this.ncols;
    ctx.clearRect(0, 0, W, H);
    // 底色(纸带暗色)
    ctx.fillStyle = '#191d24';
    ctx.fillRect(this.labelW, this.rulerH, W - this.labelW, H - this.rulerH - 6);
    // 音轨带(黑键列微暗)
    for (let c = 0; c < ncols; c++) {
      const sharp = /#/.test(this.names[c] || '');
      if (sharp) {
        ctx.fillStyle = 'rgba(255,255,255,0.03)';
        ctx.fillRect(this.labelW, this.rulerH + c * this.cell, W - this.labelW, this.cell);
      }
    }
    // 纵向分隔线(每拍 + 每小节)
    const rows = Math.max(this.rows, 1);
    ctx.textAlign = 'center';
    for (let r = 0; r <= rows; r++) {
      const x = this.labelW + r * this.cell;
      const isMeasure = this.spb > 0 && r % (this.spb * 4) === 0;
      const isBeat = this.spb > 0 && r % this.spb === 0;
      ctx.strokeStyle = isMeasure ? 'rgba(232,176,75,0.55)' :
                        isBeat ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.045)';
      ctx.lineWidth = isMeasure ? 2 : 1;
      ctx.beginPath(); ctx.moveTo(x, this.rulerH); ctx.lineTo(x, H - 6); ctx.stroke();
      if (isMeasure && r > 0) {
        ctx.fillStyle = 'rgba(255,255,255,0.6)';
        ctx.font = '10px Consolas,monospace';
        ctx.fillText(this.fmtTime(r * this.stepS), x, 10);
      }
    }
    // 横向音轨线
    for (let c = 0; c <= ncols; c++) {
      const y = this.rulerH + c * this.cell;
      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.beginPath(); ctx.moveTo(this.labelW, y); ctx.lineTo(W, y); ctx.stroke();
    }
    // 左侧音名标签
    ctx.textAlign = 'right'; ctx.font = '11px Consolas,monospace';
    for (let c = 0; c < ncols; c++) {
      const y = this.rulerH + (c + 0.5) * this.cell;
      const sharp = /#/.test(this.names[c] || '');
      ctx.fillStyle = sharp ? '#8fd0ff' : '#dde3ea';
      ctx.fillText((this.names[c] || c), this.labelW - 6, y + 4);
    }
    // 孔
    const r = Math.max(1.6, this.cell * 0.34);
    for (const h of this.holes) {
      const cx = this.rowToX(h.row), cy = this.colToY(h.col);
      ctx.fillStyle = '#f4f1e8';
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = '#00000066'; ctx.lineWidth = 1;
      ctx.stroke();
    }
    // 播放头
    if (this.playheadRow >= 0) {
      const x = this.labelW + this.playheadRow * this.cell;
      ctx.strokeStyle = '#3ecf8e'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x, this.rulerH); ctx.lineTo(x, H - 6); ctx.stroke();
    }
    // 左下信息
    ctx.textAlign = 'left'; ctx.fillStyle = 'rgba(255,255,255,0.35)';
    ctx.font = '10px Consolas,monospace';
    ctx.fillText(`${rows} 步 × ${ncols} 音 · ${this.bpm} BPM × ${this.spb}/拍`, 8, H - 2);
  }

  fmtTime(s) {
    s = Math.max(0, s);
    const m = Math.floor(s / 60), ss = Math.floor(s % 60);
    return `${m}:${String(ss).padStart(2, '0')}`;
  }

  // ---- 交互 ----
  _bind() {
    let mode = null, sx = 0, sy = 0, eraseLive = null;
    const cv = this.cv;
    cv.addEventListener('mousedown', e => {
      const p = this._pos(e);
      if (p.col < 0 || p.col >= this.ncols) return;
      mode = 'drag';
      sx = p.row; sy = p.col; eraseLive = null;
      if (this._tool === 'erase') { this._rect = { row0: sx, col0: sy, row1: sx, col1: sy }; this._dragDraw(); }
      else this._sendToggle(p.row, p.col);
    });
    cv.addEventListener('mousemove', e => {
      if (mode !== 'drag' || this._tool !== 'erase') return;
      const p = this._pos(e);
      this._rect = { row0: Math.min(sx, p.row), col0: Math.min(sy, p.col),
                     row1: Math.max(sx, p.row), col1: Math.max(sy, p.col) };
      this._dragDraw();
    });
    const up = () => {
      if (mode === 'drag' && this._tool === 'erase' && this._rect) {
        this._sendErase(this._rect);
      }
      mode = null; this._rect = null; this.draw();
    };
    cv.addEventListener('mouseup', up);
    cv.addEventListener('mouseleave', up);
    // 滚轮缩放(Ctrl/直接)
    this.wrap.addEventListener('wheel', e => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      this.setZoom(this.cell * (e.deltaY < 0 ? 1.15 : 1 / 1.15));
    }, { passive: false });
  }
  _pos(e) {
    const r = this.cv.getBoundingClientRect();
    return { row: this.xToRow(e.clientX - r.left), col: this.yToCol(e.clientY - r.top) };
  }
  _dragDraw() {
    const r = this._rect;
    this.draw();
    if (!r) return;
    const ctx = this.ctx;
    ctx.fillStyle = 'rgba(229,83,75,0.22)';
    const x = this.labelW + r.row0 * this.cell, y = this.rulerH + r.col0 * this.cell;
    ctx.fillRect(x, y, (r.row1 - r.row0 + 1) * this.cell, (r.col1 - r.col0 + 1) * this.cell);
    ctx.strokeStyle = '#e5534b'; ctx.strokeRect(x, y, (r.row1 - r.row0 + 1) * this.cell, (r.col1 - r.col0 + 1) * this.cell);
  }
  setTool(t) { this._tool = t; }
  setPlayhead(row, scrollInto = true) {
    this.playheadRow = row;
    if (scrollInto && row >= 0) {
      const x = this.labelW + row * this.cell;
      const wr = this.wrap;
      if (x < wr.scrollLeft + 30 || x > wr.scrollLeft + wr.clientWidth - 30)
        wr.scrollLeft = Math.max(0, x - wr.clientWidth / 2);
    }
    this.draw();
  }
  setZoom(factor) {
    const next = Math.min(this.maxCell(), Math.max(3, factor));
    if (next === this.cell) return;
    const c = this.wrap.clientWidth / 2 + this.wrap.scrollLeft;
    const anchorRow = (c - this.labelW) / this.cell;
    this.cell = next;
    this.layout();
    if (anchorRow >= 0) this.wrap.scrollLeft = Math.max(0, anchorRow * this.cell + this.labelW - this.wrap.clientWidth / 2);
    this.draw();
  }
  fit() {
    if (this.rows <= 0) return;
    const avail = Math.max(200, this.wrap.clientWidth - 30 - this.labelW);
    this.setZoom2(Math.min(16, Math.max(5, Math.floor(avail / this.rows))));
  }
  setZoom2(v) { this.cell = v; this.layout(); this.draw(); }

  // 回调由 app 注入
  onToggle = null;   // (row, col) => void
  onErase = null;    // (row0,row1,col0,col1) => void
  _sendToggle(row, col) { if (this.onToggle && row >= 0) this.onToggle(row, col); }
  _sendErase(r) { if (this.onErase) this.onErase(r.row0, r.row1, r.col0, r.col1); }
}
