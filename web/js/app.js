// 主控: 导入 → 识别 → 量化 → 纸带编辑 → 导出
import { TapeView } from './tapeview.js';
import { drawWaveform, playPluck, buildTapeBuffer, playTapeBuffer, audioCtx } from './audiofx.js';

const $ = s => document.querySelector(s);
const state = {
  session: null, tape: null, tableNotes: [], engines: [],
  playing: null, raf: 0,
};

async function api(url, opts = {}) {
  const res = await fetch(url, opts);
  let body = null;
  try { body = await res.json(); } catch { /* 非JSON */ }
  if (!res.ok) throw new Error((body && (body.detail || body.error)) || `HTTP ${res.status}`);
  return body;
}

function toast(msg, isErr = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (isErr ? ' err' : '');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add('hidden'), 3500);
}

// ---------------- 视图初始化 ----------------
const view = new TapeView($('#tapeCanvas'), $('#tapeWrap'));
view.setTool('toggle');

function setTapeFromServer(tape) {
  state.tape = tape;
  view.setTape(tape);
  const rows = Math.max(1, tape.rows);
  const ph = $('#playhead');
  ph.max = String(rows - 1); ph.value = '0';
  $('#timeLabel').textContent = '0:00';
  $('#tapeStats').textContent =
    `共 ${tape.rows} 步(时间步) × 30 音列 · 孔数 ${tape.hole_count} · 时长约 ${tape.duration_seconds}s ` +
    `· 参数 BPM ${tape.bpm}, 每拍 ${tape.steps_per_beat} 格 · 单格 ${tape.step_seconds}s`;
  const has = tape.hole_count > 0;
  ['#expJsonBtn', '#expCsvBtn', '#expSvgBtn', '#expPngBtn', '#expMidiBtn', '#gcodeBtn',
   '#playBtn', '#clearBtn'].forEach(
    s => $(s).disabled = !has);
}

function setEngineBadges(list) {
  $('#engineBadges').innerHTML = list.map(e =>
    `<span class="badge ${e.available ? 'ok' : 'no'}" title="${(e.reason || '').replace(/"/g, '&quot;')}">${e.available ? '✓' : '✗'} ${e.name}</span>`).join('');
}

function fillEngines(list) {
  const sel = $('#engineSel');
  sel.innerHTML = '';
  const ok = list.filter(e => e.available);
  const no = list.filter(e => !e.available);
  const unav = $('#engineUnavail');
  if (!ok.length) {
    toast('当前没有可用的识别引擎 —— 请看引擎原因。', true);
    unav.classList.remove('hidden');
    unav.innerHTML = '✗ 没有可用引擎：<br>' + (no.length
      ? no.map(e => `· ${e.name}：${e.reason || '不可用'}`).join('<br>')
      : '· 列表为空');
    return;
  }
  for (const e of ok) {
    const o = document.createElement('option');
    o.value = e.id; o.textContent = e.name;
    sel.appendChild(o);
  }
  // 不可用的引擎并列展示 + 原因(供"为什么这台不能选"提示)
  if (no.length) {
    unav.classList.remove('hidden');
    unav.innerHTML = '✗ 不可用引擎及原因：<ul style="margin:2px 0 0 16px">' +
      no.map(e => `<li><b>${e.name}</b> — <span class="muted">${e.reason || e.hint || '不可用'}</span></li>`).join('') + '</ul>';
  } else {
    unav.classList.add('hidden');
  }
  $('#engineHint').textContent = ok[0].hint || '';
  sel.onchange = () => {
    const cur = [...ok].find(e => e.id === sel.value);
    $('#engineHint').textContent = (cur && (cur.hint || '')) || '';
  };
}

// ---------------- ① 导入 ----------------
async function importAudio(file) {
  toast(`解码 ${file.name} …`);
  try {
    const sess = await api('/api/audio', {
      method: 'POST',
      headers: { 'X-File-Name': encodeURIComponent(file.name) },
      body: file,
    });
    state.session = sess;
    $('#audioInfo').textContent =
      `${sess.file_name} · ${sess.duration_s.toFixed(1)}s · ${sess.sr}Hz · ${sess.source_format.toUpperCase()}`;
    $('#audioInfo').classList.remove('hidden');
    $('#waveCanvas').classList.remove('hidden');
    drawWaveform($('#waveCanvas'), sess.peaks);
    $('#transcribeBtn').disabled = false;
    $('#quantizeBtn').disabled = true;
    toast(`已导入: ${sess.file_name}`);
  } catch (e) {
    toast('导入失败: ' + e.message, true);
  }
}

const dz = $('#dropzone');
dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('over'); });
dz.addEventListener('dragleave', () => dz.classList.remove('over'));
dz.addEventListener('drop', e => {
  e.preventDefault(); dz.classList.remove('over');
  const f = e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) importAudio(f);
});
$('#fileInput').addEventListener('change', e => {
  const f = e.target.files && e.target.files[0];
  if (f) importAudio(f);
  e.target.value = '';
});

// 载入外部高级引擎的识别结果 JSON(tools/*_events.json 或裸事件数组)
$('#notesFile').addEventListener('change', async e => {
  const f = e.target.files && e.target.files[0];
  e.target.value = '';
  if (!f) return;
  try {
    const txt = await f.text();
    const data = JSON.parse(txt);
    const events = Array.isArray(data) ? data : (data.events || []);
    const res = await api('/api/notes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ engine: data.engine || f.name, events }),
    });
    $('#notesSummary').textContent =
      `✓ 已载入外部识别结果: ${res.count} 个音符 (${data.engine || f.name})。请到③重新量化。`;
    $('#notesSummary').classList.remove('hidden');
    $('#quantizeBtn').disabled = false;
    $('#notesLoadMsg').textContent = `时长≈${res.duration_s.toFixed(1)}s`;
    toast(`已载入 ${res.count} 个音符`);
  } catch (err) {
    toast('载入失败: ' + err.message, true);
  }
});

// ---------------- MIDI 乐谱选轨(载入 .mid -> 提取所选乐器轨音符) ----------------
let _midiAnalysis = null;
let _midiBpmEdited = false;
$('#bpmIn').addEventListener('input', () => { _midiBpmEdited = true; });

function drawMidiTracks(an) {
  const box = $('#midiTracks');
  box.innerHTML = '';
  if (!an.tracks.length) {
    box.innerHTML = '<span class="muted">未发现含音符的乐器轨</span>';
    return;
  }
  for (const t of an.tracks) {
    const lab = document.createElement('label');
    lab.style.display = 'inline-flex'; lab.style.alignItems = 'center'; lab.style.gap = '4px';
    lab.innerHTML = `<input type="checkbox" data-idx="${t.idx}" ${t.is_drum ? 'disabled' : ''}>
      <span title="${t.name}">${t.name}</span>
      <span class="muted small">${t.note_count}音${t.is_drum ? ' · 鼓(无音高, 通常不可用)' : ''}</span>`;
    box.appendChild(lab);
  }
  box.onchange = () => {
    $('#midiUseBtn').disabled =
      ![...box.querySelectorAll('input:checked:not(:disabled)')].length;
  };
}

$('#midiFile').addEventListener('change', async e => {
  const f = e.target.files && e.target.files[0];
  e.target.value = '';
  if (!f) return;
  $('#midiMsg').textContent = '解析中…';
  try {
    const an = await api('/api/midi', {
      method: 'POST',
      headers: { 'X-File-Name': encodeURIComponent(f.name) },
      body: f,
    });
    _midiAnalysis = an;
    $('#midiInfo').textContent =
      `${f.name} · 约${an.tempo_bpm} BPM · ${an.duration_s.toFixed(1)}s · ${an.tracks.length}条乐器轨`;
    drawMidiTracks(an);
    $('#midiPanel').classList.remove('hidden');
    $('#midiHint').textContent = '勾选想要进纸带的乐器轨(可多选; 鼓/打击乐一般跳过)。';
    $('#midiUseBtn').disabled = true;
    // 若用户没手改过 BPM, 用 MIDI 自带 tempo 提示到③
    if (!_midiBpmEdited && $('#bpmIn').value === '120') {
      $('#bpmIn').value = Math.round(an.tempo_bpm);
      $('#midiHint').textContent =
        `已把③速度设为 MIDI 自带 ${Math.round(an.tempo_bpm)} BPM(可自行改)。勾选轨道后点下方按钮。`;
    }
    $('#midiMsg').textContent = `解析完成: ${an.tracks.length}轨`;
  } catch (err) {
    $('#midiMsg').textContent = '解析失败: ' + err.message;
    toast('MIDI 解析失败: ' + err.message, true);
  }
});

$('#midiUseBtn').addEventListener('click', async () => {
  const checked = [...document.querySelectorAll('#midiTracks input:checked:not(:disabled)')]
    .map(i => parseInt(i.dataset.idx, 10));
  if (!checked.length) { toast('请先勾选乐器轨', true); return; }
  try {
    const res = await api('/api/midi/select', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tracks: checked }),
    });
    $('#midiPanel').classList.add('hidden');
    $('#notesSummary').textContent =
      `✓ 已从 MIDI 选中 ${checked.length} 条乐器轨载入 ${res.count} 个音符。请到③量化。`;
    $('#notesSummary').classList.remove('hidden');
    $('#quantizeBtn').disabled = false;
    $('#midiMsg').textContent = `已载入 ${res.count} 个音符(时长≈${res.duration_s.toFixed(1)}s)`;
    toast(`MIDI 载入 ${res.count} 个音符`);
  } catch (err) {
    toast('载入失败: ' + err.message, true);
  }
});

// ---------------- ② 识别 ----------------
$('#transcribeBtn').addEventListener('click', async () => {
  const engine = $('#engineSel').value;
  const conf = parseFloat($('#confIn').value) || 0.1;
  const params = engine === 'basic_pitch'
    ? { min_amplitude: conf, onset_threshold: 0.5, frame_threshold: 0.3, minimum_note_length_ms: 80 }
    : { onset_threshold: 0.5, max_polyphony: 3, min_freq: 65, max_freq: 2500 };
  $('#transcribeBtn').disabled = true;
  $('#progressWrap').classList.remove('hidden');
  $('#progFill').style.width = '2%';
  $('#progMsg').textContent = '提交任务…';
  try {
    const { job_id } = await api('/api/transcribe', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ engine, params }),
    });
    pollJob(job_id, engine);
  } catch (e) {
    $('#transcribeBtn').disabled = false;
    toast('识别启动失败: ' + e.message, true);
  }
});

function pollJob(jobId, engine) {  const t = setInterval(async () => {
    try {
      const j = await api('/api/jobs/' + jobId);
      $('#progFill').style.width = (j.progress * 100).toFixed(0) + '%';
      $('#progMsg').textContent = j.message || j.status;
      if (j.status === 'done') {
        clearInterval(t);
        $('#progressWrap').classList.add('hidden');
        $('#transcribeBtn').disabled = false;
        const n = (j.result && j.result.count) || 0;
        $('#notesSummary').textContent = `✓ 识别完成: ${n} 个音符 (引擎: ${engine})。可进入③编曲映射。`;
        $('#notesSummary').classList.remove('hidden');
        $('#quantizeBtn').disabled = false;
        toast(`识别完成: ${n} 个音符`);
      } else if (j.status === 'error') {
        clearInterval(t);
        $('#progressWrap').classList.add('hidden');
        $('#transcribeBtn').disabled = false;
        toast('识别失败: ' + j.error, true);
        $('#notesSummary').textContent = '识别失败: ' + j.error;
        $('#notesSummary').classList.remove('hidden');
      }
    } catch (e) {
      clearInterval(t);
      $('#transcribeBtn').disabled = false;
      toast('轮询出错: ' + e.message, true);
    }
  }, 600);
}

// ---------------- Omnizart HTTP 引擎服务配置(可选用才显示; 不可用给原因) ----------------
async function testOmniService() {
  const url = ($('#omniSvc').value || '').trim();
  const msg = $('#omniSvcMsg');
  const btn = $('#omniSvcConn');
  btn.disabled = true; msg.textContent = '测试…';
  try {
    const res = await api('/api/engines/omnizart/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    if (res.available) {
      msg.textContent = `✓ Omnizart 服务可用 (device=${res.device || '?'} model=${res.model || '-'})`;
      toast('Omnizart 服务已连接');
    } else {
      msg.textContent = '✗ ' + (res.reason || '不可用');
      toast('Omnizart 服务不可用: ' + (res.reason || ''), true);
    }
    await refreshEnginesUI();
  } catch (e) { msg.textContent = '错误: ' + e.message; toast('测试连接失败: ' + e.message, true); }
  finally { btn.disabled = false; }
}

async function refreshEnginesUI() {
  // 用 /api/engines(后端重新给出可达性)刷新选项/徽标/原因
  try {
    const data = await api('/api/engines');
    state.engines = data.engines;
    setEngineBadges(state.engines);
    fillEngines(state.engines);
    if (!state.engines.some(e => e.available)) { $('#transcribeBtn').disabled = true; }
  } catch (_) { /* 保底: 保持现状 */ }
}

$('#omniSvcConn').addEventListener('click', testOmniService);
$('#omniSvc').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); testOmniService(); } });

// ---------------- ③ 量化 ----------------
$('#quantizeBtn').addEventListener('click', async () => {
  const body = {
    bpm: parseFloat($('#bpmIn').value) || 120,
    steps_per_beat: parseInt($('#spbSel').value, 10),
    min_confidence: parseFloat($('#confIn').value) || 0,
    out_of_range: $('#oorSel').value,
    min_gap_steps: parseInt($('#gapIn').value, 10) || 0,
    auto_transpose: parseInt($('#autoTrSel').value, 10) || 0,
    transpose_semitones: parseInt($('#trIn').value, 10) || 0,
    max_midi: parseFloat($('#maxMidiIn').value) || 127,
    min_midi: parseFloat($('#minMidiIn').value) || 0,
  };
  try {
    const res = await api('/api/quantize', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    setTapeFromServer(res.tape);   // 内部按 hole_count 统一开关导出/播放按钮(含 G-code)
    state.tableNotes = res.table.notes;
    view.setTable(state.tableNotes);
    view.fit();
    renderStats(res.stats);
    toast(`已生成纸带: ${res.tape.hole_count} 孔`);
  } catch (e) {
    toast('量化失败: ' + e.message, true);
  }
});

function renderStats(s) {
  const el = $('#arrangeStats');
  el.classList.remove('hidden');
  el.textContent =
    `音符总数 ${s.total_events} → 保留 ${s.kept} 孔 | ` +
    `低于置信度 ${s.dropped_low_conf} | 八度鬼影抑制 ${s.ghost_dropped} | ` +
    `自动移调 ${s.transpose_used > 0 ? '+' : ''}${s.transpose_used} 半音(鲁棒) | ` +
    `八度折叠 ${s.folded} | 夹取 ${s.clamped} | ` +
    `超范围丢弃 ${s.out_of_range_skipped} | 重复 ${s.duplicates} | 过近合并 ${s.too_close} | ` +
    `极高点缀音 ${s.extreme_high} / 极低 ${s.extreme_low}`;
  const w = $('#warnList');
  if (s.warnings && s.warnings.length) {
    w.classList.remove('hidden');
    w.textContent = s.warnings.map(x =>
      `· ${x.reason} (${x.freq ? x.freq + 'Hz' : ''}${x.col !== undefined ? ' 列' + x.col : ''})`).join('\n');
  } else {
    w.classList.add('hidden');
  }
}

// ---------------- ④ 编辑交互 ----------------
view.onToggle = async (row, col) => {
  try {
    const res = await api('/api/tape/edit', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actions: [{ op: 'toggle', row, col }] }),
    });
    setTapeFromServer(res.tape);
    if (res.report[0] && res.report[0].added) playPluck(state.tableNotes[col]?.freq || 0);
  } catch (e) { toast(e.message, true); }
};
view.onErase = async (row0, row1, col0, col1) => {
  try {
    const res = await api('/api/tape/edit', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actions: [{ op: 'remove_region', row0, row1, col0, col1 }] }),
    });
    setTapeFromServer(res.tape);
  } catch (e) { toast(e.message, true); }
};
$('#toolSel').addEventListener('change', e => view.setTool(e.target.value));
$('#clearBtn').addEventListener('click', async () => {
  if (!confirm('确定清空整张纸带?')) return;
  try {
    const res = await api('/api/tape/edit', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actions: [{ op: 'clear' }] }),
    });
    setTapeFromServer(res.tape);
    stopPlay();
  } catch (e) { toast(e.message, true); }
});
$('#zoomInBtn').addEventListener('click', () => view.setZoom(view.cell * 1.25));
$('#zoomOutBtn').addEventListener('click', () => view.setZoom(view.cell / 1.25));
$('#fitBtn').addEventListener('click', () => view.fit());

// ---------------- 试听播放 ----------------
function freqList() { return state.tableNotes.map(n => n.freq); }

function stopPlay() {
  if (state.playing) {
    try { state.playing.source.stop(); } catch { /* */ }
    state.playing = null;
  }
  cancelAnimationFrame(state.raf);
  $('#playBtn').textContent = '▶ 试听播放';
  view.setPlayhead(-1);
}

$('#playBtn').addEventListener('click', () => {
  if (state.playing) { stopPlay(); return; }
  if (!state.tape || state.tape.hole_count === 0) return;
  audioCtx();
  const buf = buildTapeBuffer(state.tape, freqList());
  const startRow = parseInt($('#playhead').value, 10) || 0;
  const offset = startRow * state.tape.step_seconds;
  const { source } = playTapeBuffer(buf, offset, () => {
    state.playing = null; $('#playBtn').textContent = '▶ 试听播放';
    view.setPlayhead(-1);
  });
  const rows = Math.max(1, state.tape.rows);
  const t0 = audioCtx().currentTime;
  state.playing = { source };
  $('#playBtn').textContent = '⏸ 停止';
  const tick = () => {
    if (!state.playing) return;
    const cur = offset + (audioCtx().currentTime - t0);
    const row = Math.min(rows - 1, cur / state.tape.step_seconds);
    $('#playhead').value = String(Math.floor(row));
    $('#timeLabel').textContent = view.fmtTime(cur);
    if (row % 4 < 0.05 || state.playing._force) view.setPlayhead(Math.floor(row), true);
    state.playing._force = false;
    state.raf = requestAnimationFrame(tick);
  };
  tick();
});
$('#stopBtn').addEventListener('click', stopPlay);
$('#playhead').addEventListener('input', e => {
  stopPlay();
  const row = parseInt(e.target.value, 10) || 0;
  $('#timeLabel').textContent = view.fmtTime(row * (state.tape?.step_seconds || 0.0625));
  view.setPlayhead(row, true);
});
window.addEventListener('keydown', e => {
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
  if (e.code === 'Space') { e.preventDefault(); $('#playBtn').click(); }
  else if (e.code === 'KeyE') {
    const s = $('#toolSel');
    s.value = s.value === 'erase' ? 'toggle' : 'erase';
    view.setTool(s.value);
  }
});

// ---------------- ⑤ 导出 ----------------
function downloadFrom(url, name) {
  const a = document.createElement('a');
  a.href = url; a.download = name || ''; document.body.appendChild(a); a.click(); a.remove();
}
$('#expJsonBtn').addEventListener('click', () => downloadFrom('/api/export/json'));
$('#expCsvBtn').addEventListener('click', () => downloadFrom('/api/export/csv'));
$('#expSvgBtn').addEventListener('click', () => downloadFrom('/api/export/svg'));
$('#expMidiBtn').addEventListener('click', () => downloadFrom('/api/export/midi'));
$('#expPngBtn').addEventListener('click', () => {
  const cv = $('#tapeCanvas');
  if (!cv.width) return;
  const a = document.createElement('a');
  a.download = 'tape_preview.png';
  a.href = cv.toDataURL('image/png');
  document.body.appendChild(a); a.click(); a.remove();
});
$('#gcodeBtn').addEventListener('click', async () => {
  // 先请求统计(顺便校验后端能生成), 再走浏览器下载
  try {
    const res = await api('/api/gcode', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const s = res.stats || {};
    toast(`G-code 已生成: ${s.holes} 孔 / ${s.rows_with_holes} 有孔行 / 纸带 ${s.tape_len_mm}mm / 约 ${s.total_minutes} 分钟`);
  } catch (e) {
    toast('G-code 生成失败: ' + e.message, true);
    return;
  }
  downloadFrom('/api/export/gcode');
});

// ---------------- 启动 ----------------
async function boot() {
  try {
    const meta = await api('/api/meta');
    state.engines = meta.engines;
    setEngineBadges(meta.engines);
    fillEngines(meta.engines);
    if (meta.table) {
      state.tableNotes = meta.table.notes;
      view.setTable(state.tableNotes);
    }
    // 恢复上次工程
    const proj = await api('/api/project');
    if (proj.tape) {
      setTapeFromServer(proj.tape);
      const has = proj.tape.hole_count > 0;
      $('#expJsonBtn').disabled = !has; $('#playBtn').disabled = !has;
      $('#tapeStats').textContent && $('#tapeWrap').classList.remove('hidden');
    }
    if (proj.session) {
      state.session = proj.session;
      $('#audioInfo').textContent =
        `${proj.session.file_name} · ${proj.session.duration_s.toFixed(1)}s · ${proj.session.sr}Hz`;
      $('#audioInfo').classList.remove('hidden');
      if (proj.session.peaks && proj.session.peaks.length) {
        $('#waveCanvas').classList.remove('hidden');
        drawWaveform($('#waveCanvas'), proj.session.peaks);
      }
      $('#transcribeBtn').disabled = false;
      if (proj.session.note_count > 0) {
        $('#notesSummary').textContent =
          `上次识别: ${proj.session.note_count} 个音符 (引擎 ${proj.session.notes_engine})`;
        $('#notesSummary').classList.remove('hidden');
        $('#quantizeBtn').disabled = false;
      }
    }
    const g = meta.engines.find(e => e.id === 'basic_pitch');
    if (g && !g.available) toast('注意: Basic Pitch 不可用, 请见 README 安装说明', true);
  } catch (e) {
    toast('启动失败(后端未就绪?): ' + e.message, true);
  }
}

boot();
