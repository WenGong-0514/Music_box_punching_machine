// 音频工具: 波形绘制 + 纸带合成试听(简易八音盒音色)
let _ctx = null;
export function audioCtx() {
  if (!_ctx) _ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (_ctx.state === 'suspended') _ctx.resume();
  return _ctx;
}

export function drawWaveform(canvas, peaks) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.fillStyle = '#10141a'; ctx.fillRect(0, 0, w, h);
  if (!peaks || !peaks.length) {
    ctx.fillStyle = '#4a5563'; ctx.font = '13px sans-serif';
    ctx.fillText('(无波形)', 10, h / 2 + 5); return;
  }
  ctx.strokeStyle = '#5aa7ff'; ctx.lineWidth = 1;
  ctx.beginPath();
  const n = peaks.length;
  for (let i = 0; i < n; i++) {
    const x = i / (n - 1) * w;
    const y0 = (1 - (peaks[i].max + 1) / 2) * h;
    const y1 = (1 - (peaks[i].min + 1) / 2) * h;
    ctx.moveTo(x, y0); ctx.lineTo(x, y1);
  }
  ctx.stroke();
  ctx.fillStyle = 'rgba(255,255,255,0.5)';
  ctx.font = '10px Consolas,monospace';
  ctx.fillText(`${peaks[n - 1].t.toFixed(1)}s`, w - 60, h - 6);
}

// 生成"八音盒音"干样本混合进 buffer(时间/采样率对齐)
function addPluck(buf, offsetSec, freq, gain = 0.55) {
  const sr = buf.sampleRate, n = buf.length;
  const off = Math.floor(offsetSec * sr);
  if (freq <= 0 || off >= n) return;
  const dur = Math.min(1.1, n / sr - offsetSec);
  if (dur <= 0) return;
  const len = Math.floor(dur * sr);
  const partials = [[1, 1, 0.085], [2, 0.55, 0.05], [3, 0.28, 0.035], [4.01, 0.14, 0.03], [5.08, 0.07, 0.022]];
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) {
    const t = i / sr;
    let v = 0;
    for (const [mult, amp, tau] of partials) {
      const f = freq * mult;
      const env = Math.exp(-t / tau);
      v += amp * Math.sin(2 * Math.PI * f * t) * env;
    }
    const idx = off + i;
    if (idx < n) data[idx] += v * gain / 2.2;
  }
}

let _lastBuf = null, _lastKey = '';
export function buildTapeBuffer(tape, freqs) {
  // key: 依据内容缓存
  const key = JSON.stringify({ h: tape.holes, f: tape.bpm, s: tape.steps_per_beat, n: freqs.length });
  if (_lastKey === key && _lastBuf) return _lastBuf;
  const ctx = audioCtx();
  const stepS = 60 / (tape.bpm * Math.max(1, tape.steps_per_beat));
  const rows = tape.holes.reduce((m, h) => Math.max(m, h.row), 0) + 1;
  const total = Math.max(1, (rows + 2) * stepS);
  const buf = ctx.createBuffer(1, Math.ceil(total * ctx.sampleRate), ctx.sampleRate);
  for (const h of tape.holes) {
    const f = freqs[h.col] || 0;
    addPluck(buf, h.row * stepS, f);
  }
  // 限幅
  const d = buf.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = Math.max(-1, Math.min(1, d[i]));
  _lastKey = key; _lastBuf = buf;
  return buf;
}

export function playTapeBuffer(buf, offsetSec = 0, onended = null) {
  const ctx = audioCtx();
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.connect(ctx.destination);
  src.onended = onended;
  src.start(0, offsetSec);
  return { source: src, startedAt: ctx.currentTime, offset: offsetSec };
}

export function playPluck(freq, dur = 1.0) {
  const ctx = audioCtx();
  const buf = ctx.createBuffer(1, Math.ceil(dur * ctx.sampleRate), ctx.sampleRate);
  addPluck(buf, 0, freq, 0.8);
  const src = ctx.createBufferSource();
  src.buffer = buf; src.connect(ctx.destination); src.start();
}
