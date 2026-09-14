# 开发者文档 — MusicBox Tape Studio

> 面向接手/二次开发的工程说明。用户向说明见根目录 [README.md](../README.md);
> 打孔机与 G-code 细节见 [MACHINE.md](MACHINE.md);引擎评测见 [ENGINES.md](ENGINES.md);
> 多机环境与历史变更见 [HISTORY.md](HISTORY.md)。

---

## 1. 项目定位与总数据流

面向"30 音纸带八音盒打孔机"的上位机:把音乐变成**纸带孔位**,并生成**打孔 G-code**。
形态是**本地 Web 应用**(Python FastAPI 后端 + 浏览器原生 JS 前端),`run.bat` 启动,访问 `http://127.0.0.1:8765`。

核心数据流(所有环节都围绕中间的"事件"与"纸带"两种结构):

```
音频文件 ──audio_io.decode──► wav 缓存
                                  │
              ┌─── 音频识别(引擎) ─┴─── MIDI 乐谱导入(选轨)
              ▼                              ▼
        events[]  ───────────────────────  events[]
       {start_s,dur_s,freq,confidence[,midi,velocity,program]}
                              │
                              ▼  quantize.quantize_to_tape(table, bpm, steps_per_beat, ...)
                        Tape {holes:[{row,col}], bpm, steps_per_beat}
                              │
        ┌─────────────┬───────┴────────┬──────────────┬─────────────┐
        ▼             ▼                ▼              ▼             ▼
   GUI 画布编辑   导出 JSON/CSV    导出 SVG/PNG   导出 MIDI    导出 G-code(GRBL)
     (④)                       (⑤, /api/export/*)            (server/gcode.py)
```

关键设计取舍:
- **一步一个中间模型**:引擎只产出 `events`;量化只消费 `events` 产出 `Tape`;导出只消费 `Tape`。
  因此"音频识别"与"MIDI 乐谱导入"可以共用同一条下游链路(这也是加 MIDI 功能只花了很少改动的原因)。
- **纸带语义**:一个孔 = 一次拨弦;音的时值由孔间距表达,孔本身不表音长。所以 `Tape` 只用 `(row, col)`。

---

## 2. 目录结构与模块职责

```
server/                  FastAPI 后端(全部业务逻辑)
  main.py                入口: 建 app、挂静态目录、启动时从 data/project.json 恢复工程、uvicorn 启动
  api.py                 全部 REST 端点(见 §4)
  state.py               AppState(单用户会话状态) / Session / Job / JobManager; project.json 持久化
  notetable.py           30 音音表: 标签解析 → MIDI/频率、find_nearest、fold_into_range、序列化
  tape.py                纸带模型: holes 增删/去重/区域擦除/统计 + JSON/CSV/SVG 序列化
  quantize.py            events → Tape: 鬼影抑制/自动移调/折叠/夹取/丢弃/去重/最小间隔/音域过滤
  audio_io.py            音频解码(miniaudio → soundfile → ffmpeg 兜底) + 波形 peaks
  midi_import.py         MIDI 乐谱: 轨清单分析(音色/音符数/音域/是否鼓) + 选轨 → events
  midi_export.py         纸带 → 标准 MIDI(.mid),供钢琴软件/DAW 演奏
  gcode.py               纸带 → 打孔 G-code(GRBL): 路径规划 + 参数 + 时长/行程预估
  engines/
    __init__.py          引擎注册表 available_engines() / 调度 transcribe_with()
    basicpitch_engine.py Spotify Basic Pitch(优先 ONNX runtime, 支持 dml/auto 设备)
    dsp_engine.py        轻量兜底: STFT + 谐波求和的多音估计(仅需 numpy/scipy/soundfile)
    omnizart_engine.py   本地 TensorFlow 版 Omnizart(历史实现, 现由 HTTP 服务路径取代, 保留备用)
    remote_omnizart.py   Omnizart HTTP 引擎服务的客户端 + 健康探测(带 TTL 缓存)

web/                     前端(零构建依赖, 原生 ES Module)
  index.html             五步界面 + Omnizart 服务地址栏 + MIDI 乐谱导入面板
  js/app.js              主控: 导入/识别/量化/编辑/试听/导出、引擎与 MIDI 交互
  js/tapeview.js         纸带画布: 缩放、点击加删孔、拖拽擦除、播放头、音名列标签
  js/audiofx.js          波形绘制 + WebAudio 拨弦合成试听
  css/style.css

tools/                   命令行工具(开发/评测/验证)
  make_test_audio.py     合成测试音频(含超音域片段)
  e2e_check.py           全流程冒烟: 音频 → 识别 → 量化 → 导出
  eval_pipeline.py       单曲识别并存档为 events JSON
  gt_eval.py             合成已知真值集的音符级评估
  omnizart_run.py        本地 TF 版 Omnizart CLI
  omnizart_remote.py     远程 Omnizart HTTP 服务 CLI(上传音频→取回 events.json, 凭证走环境变量)
  bytedance_run.py       ByteDance 钢琴转录对比
  source_separate.py     Demucs 源分离(htdemucs / htdemucs_6s)
  compare_to_score.py    与参考谱面(JSON)逐音符对比
  score_parse.py         谱面 SVG/JSON 解析为统一音符表
  analyze_*.py           移调/音区/鲁棒性/音域过滤等分析脚本
  make_preflight_gcode.py 生成"两孔/边界"预校验 G-code(上机前验证坐标系)

deploy_server/           服务器侧部署(把 Omnizart 做成可远程调用的引擎服务)
  Dockerfile             CPU 镜像(CLI 转录)
  Dockerfile.portable    自包含镜像: 直接跑 HTTP 引擎服务
  omni_http.py           FastAPI 引擎服务: GET /health, POST /transcribe(multipart)
  omnizart_transcribe.py 容器内 CLI 转录
  SERVICE-INSTALL.md     让别的机器/另一个 AI 照做即可部署的安装文档
  README.md              部署与 GPU 复现记录

data/
  note_table_30note.json 30 音音表(唯一需要的核心配置; 改这里即可换音梳)
  project.json           自动存档(工程状态; 已 gitignore)
  sessions/<id>/         导入音频与解码 wav 缓存(已 gitignore)
```

---

## 3. 核心数据结构

### 3.1 事件 events(引擎/导入的统一输出)

```json
{"start_s": 0.05, "dur_s": 0.51, "freq": 261.63, "confidence": 0.71,
 "midi": 60, "velocity": 121, "program": 0, "track": 0}
```
- 必需:`start_s`(秒)、`dur_s`、`freq`(Hz)、`confidence`(0~1);
- 可选:`midi`、`velocity`、`program`、`track`(MIDI 导入会带上,量化层不使用但保留);
- 音频识别引擎只填前四项;`/api/notes` 会做归一化(容错 `start/pitch_hz/dur/velocity` 等别名)。

### 3.2 音表 NoteTable(`data/note_table_30note.json`)

```json
{"id": "...", "name": "...", "base_octave": 3, "columns": ["C","D","G","A","B","C1", ...]}
```
- 必须恰好 30 列,且 MIDI 严格递增;`base_octave` 只影响听感与折叠,不影响孔位相对布局;
- 标签解析支持 `C` / `#F1` / `F#1` / `C3`,内部统一成 `X#n`;
- 换硬件音梳 = 改这个文件(第 1 项为最低音),重启生效。

### 3.3 纸带 Tape

```json
{"format": "musicbox_tape_v1", "table_id": "...", "bpm": 160.0, "steps_per_beat": 16,
 "step_seconds": 0.0234375, "ncols": 30, "rows": 14903, "hole_count": 2618,
 "holes": [{"row": 0, "col": 2}, ...], "machine": {...}, "meta": {}}
```
- `row` = 时间步(1 格 = `60/(bpm×steps_per_beat)` 秒);`col` = 0..29 音轨;同行多列 = 和弦;
- `machine` 是导出给下一阶段的占位参数(G-code 生成不读它,读 `server/gcode.py` 的 `MachineParams`)。

### 3.4 量化统计 quantize stats(前端 ③ 会展示)

`total_events, ghost_dropped, transpose_used, shift_robust, extreme_high, extreme_low,
register_dropped, kept, dropped_low_conf, out_of_range_skipped, clamped, folded,
duplicates, too_close, warnings, final_holes`

调参与策略细节见 `quantize.py` 文档字符串(自动移调 `auto_transpose`、鲁棒移调 `shift_robust`、
音域过滤 `max_midi/min_midi`、冲突感知折叠、过近丢弃 `min_gap_steps`)。

---

## 4. 后端 API 清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 存活 + 音表是否加载 |
| GET | `/api/meta` | 应用信息、引擎列表、音表、默认参数 |
| GET | `/api/engines` | 引擎可用性(含 `reason`,供 GUI 置灰解释) |
| GET | `/api/engines/omnizart` | Omnizart 服务状态(available/device/reason/URL) |
| POST | `/api/engines/omnizart/config` | `{url}` 会话内切换服务地址并重新探测 |
| POST | `/api/audio` | 原始 body 上传音频(`X-File-Name` 头)→ 解码 + 波形 + 建会话 |
| POST | `/api/transcribe` | `{engine, params}` → 建后台 Job(线程),返回 `{job_id}` |
| GET | `/api/jobs/{id}` | 轮询任务进度/结果/错误 |
| POST | `/api/notes` | `{engine, events[]}` 载入外部识别 JSON(归一化) |
| POST | `/api/midi` | 原始 body 上传 `.mid`(`X-File-Name`)→ **乐器轨清单**(音色/音符数/音域/是否鼓/tempo) |
| POST | `/api/midi/select` | `{tracks:[idx,...]}` → 所选轨转 events 存入会话(engine=`midi:...`) |
| POST | `/api/quantize` | `{bpm, steps_per_beat, min_confidence, out_of_range, min_gap_steps, auto_transpose, ...}` → Tape + stats |
| GET | `/api/tape` | 当前纸带 + 音表 + 量化统计 |
| POST | `/api/tape/edit` | `{actions:[{op:'toggle'|'remove_region'|'clear'|'params', ...}]}` |
| GET | `/api/export/{fmt}` | `fmt ∈ json\|csv\|svg\|midi\|gcode`(下载) |
| POST | `/api/table` | `{columns[30], base_octave, name}` 替换音表 |
| GET | `/api/project` | 工程快照(会话/音符预览/纸带/统计/音表) |
| POST | `/api/gcode` | 生成打孔 G-code,返回 `{stats, lines, bytes, preview, gcode}` |

---

## 5. 引擎体系

- **注册表**:`server/engines/__init__.py: available_engines()` 返回统一描述
  `{id, name, available, hint[, reason, kind, service_url]}`;`transcribe_with(id, wav, params, progress)` 负责调度。
- **Basic Pitch**(`basicpitch_engine.py`):ONNX 优先(`onnxruntime`),`device=cpu|dml|auto`;
  Windows+py3.13 需按 README 的"wheel + --no-deps"方式安装,且需要 `setuptools<81`(运行时 `pkg_resources`)。
- **DSP**(`dsp_engine.py`):只依赖 numpy/scipy/soundfile;STFT + 谐波求和,速度极快、精度有限。
- **Omnizart**:两种形态
  1. 本地 TF(`omnizart_engine.py`,历史实现):本机需 TensorFlow + tf-keras,Windows/py3.13 上极难,已不作为主路径;
  2. **HTTP 引擎服务(当前主路径)**:`remote_omnizart.py` 探测 `OMNIZART_SERVICE_URL`(默认 `http://127.0.0.1:8766`)的
     `/health`,只有在服务可达且就绪时该引擎才出现在 GUI 可选列表;转录时把 wav POST 到 `/transcribe`。
     服务端实现见 `deploy_server/omni_http.py`,部署见 `deploy_server/SERVICE-INSTALL.md`。

> 设计要点:引擎可用性**必须能被真实探测**(不能只看权重文件是否存在)——历史上这里出过"GUI 假打勾、点了报错"的问题。

---

## 6. 机器与 G-code 层

坐标定义、参数、路径规划、上机校验流程已独立成文 👉 [MACHINE.md](MACHINE.md)。
代码入口:`server/gcode.py`(`MachineParams` / `plan` / `estimate` / `tape_to_gcode`)。

---

## 7. 本地开发与运行

```bat
:: 1) 依赖(Windows/py3.13 实测; 网络受限时加 -i 镜像)
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python -m pip install third_party\basic_pitch-0.4.0-py2.py3-none-any.whl --no-deps

:: 2) 启动(优先用工程内 .venv, 详见 run.bat)
run.bat
```

注意:
- **后端不运行 = 页面能开但所有"下载/识别"都失败**(前端会提示);下载按钮依赖后端存活。
- 前端零构建:直接改 `web/` 下文件刷新即可(静态目录由后端托管)。
- 数据落盘:导入音频 → `data/sessions/<id>/`;工程自动存档 → `data/project.json`。

### 测试与验证

```bat
python tools\make_test_audio.py                :: 生成测试音频
python tools\e2e_check.py --engine all         :: 冒烟: 音频→识别→量化→导出
python tools\make_preflight_gcode.py           :: 生成上机前两孔/边界 G-code(需 data/project.json 有纸带)
python tools\compare_to_score.py x.json        :: 与参考谱面逐音符对比
```
> Windows 控制台默认 GBK:打印 emoji/特殊字符可能报 `UnicodeEncodeError`,用
> `set PYTHONIOENCODING=utf-8`(run.bat 已设)可避免。这属控制台编码问题,不是逻辑错误。

---

## 8. 扩展指南

- **加识别引擎**:在 `server/engines/` 新建模块,实现 `transcribe(wav_path, params, progress) -> events[]`;
  在 `__init__.available_engines()` 注册(带真实可用性探测 + `reason`),在 `transcribe_with()` 加分支。
- **加导出格式**:在 `server/api.py: export()` 的 `fmt` 分支里实现内容与 media type;
  前端在 `web/index.html` ⑤ 加按钮 + `app.js` 加 `downloadFrom('/api/export/xxx')`。
- **换音表/硬件音梳**:改 `data/note_table_30note.json` 的 `columns`(30 项,升序),
  `base_octave` 调听感;若硬件列序相反,把数组倒序。
- **改机器参数/坐标**:改 `server/gcode.py: MachineParams`(纸带宽/有效区/列分布/速度/安全高度/尾部前进)。
- **接 GRBL 串口(待办)**:建议在 `server/` 新增 `serial_grbl.py`(pyserial),提供
  `connect/stream/status/feed_hold/soft_reset`;流控要点:GRBL 接收缓冲约 127 字节、
  按 `ok` 应答推进、`?` 查询状态、`!`/`~` 进给保持与恢复、`Ctrl-X` 软复位。
  长文件(本曲 16000+ 行)必须流式发送,不能一次性写入。

---

## 9. 已知问题 / 技术债

按优先级排列(**均未修复**,欢迎接手):

1. `server/notetable.py` 中 `freq_to_midi` 引用了未定义的 `math_log2`(调用即 `NameError`);
   仓库内当前无人调用(量化用自己的局部实现),属死代码隐患;`_log2` 亦未使用。
2. `server/quantize.py` 主循环里用 `for h in holes` 重新收集"同排已占列",事件数上万时是 O(n²);
   应改为增量维护 `dict[row, set[col]]`。
3. `server/audio_io.py` 顶层无条件 `import soundfile`(而 miniaudio 却是可选的),
   与"优先 miniaudio"的注释相反;建议 soundfile 也做可选导入并调整注释。
4. `server/engines/dsp_engine.py` 有未使用变量 `idx_by_freq`。
5. 仓库此前无版本管理;首次上传前建议 `git init` 并确认 `.gitignore` 生效(`git status` 不应出现
   `.venv/`、`out/`、`data/sessions/`、`*.tar`、`ncm_tools/`)。
6. `server/engines/omnizart_engine.py` 的 `is_available()` 只检查权重文件存在,
   **不要**再把它接回 GUI 可用性判断(现由 `remote_omnizart` 真实探测替代)。

---

## 10. 路线图

1. **GRBL 串口直连**:连接/开始/暂停/急停 + 流式发送 + 进度(见 §8)。
2. **分段/断点续打**:整曲 2.8m、约 30 分钟,应支持按 row 区间切分多个 G-code 文件并在段首尾回安全位。
3. **机械校准向导**:把 `MachineParams` 各参数做成界面向导 + 试打校准块(齿距/步距/安全高度实测)。
4. **编曲适配**:面向八音盒的自动编曲(主旋律提取 + 伴奏简化 + 音域搬移),减少"八度折叠"造成的失真
   (评测数据见 [ENGINES.md](ENGINES.md))。
5. **MIDI 导入增强**:多轨重叠去重/力度映射、忽略鼓轨节奏线做孔等。
