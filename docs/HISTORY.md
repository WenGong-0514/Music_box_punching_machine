# 环境适配与变更记录(历史)

> 记录多台机器上的环境状态、适配过程与已知问题(内容保持原样, 仅对内网地址/用户名做了占位化)。
> 面向当前有效状态请看 [DEVELOPMENT.md](DEVELOPMENT.md) 与 [MACHINE.md](MACHINE.md)。

---

# ⚠️ 当前存在问题 / 运行状态(工程体检结论)

> 本节为代码级 + 环境级体检结果,与上方"设计说明"区分。**结论先行:工程代码与数据本身
> 基本健康,核心编曲链路实测通过;但当前这台机器环境缺依赖,软件暂时无法启动。**

## 1. 运行环境问题(当前无法启动的直接原因)

| 项 | 现状 |
|---|---|
| Python | 仅 `%USERPROFILE%\AppData\Local\Programs\Python\Python313`(3.13.2) |
| 已装依赖 | 仅 `pip`、`uvicorn 0.48.0`、`numpy 2.2.6`、`scipy 1.16.3` |
| 缺失依赖 | `fastapi`、`python-multipart`、`soundfile`、`miniaudio`、`librosa`、`mir-eval`、`pretty-midi`、`resampy`、`onnxruntime`(requirements.txt 全部要求项) |
| run.bat 兜底路径 | 指向 `...\Python312\python.exe`,该目录**已不存在**(磁盘上只有 Python313) |

**后果**:现在执行 `run.bat` 或 `python -m server.main` 会在 import 阶段直接
`ModuleNotFoundError`;`http://127.0.0.1:8765` 当前无进程监听,Web 界面起不来。

**修复路径**(需联网,耗时较长):
```bat
python -m pip install -r requirements.txt
python -m pip install third_party\basic_pitch-0.4.0-py2.py3-none-any.whl --no-deps
python -m pip install mir-eval pretty-midi "resampy<0.4.3"
```
(其余引擎可选:Omnizart 需 `tensorflow` + `tf-keras`;DirectML 加速需 `onnxruntime-directml`;
源分离需 `torch` + `demucs` —— 详见上方「依赖安装」与「进阶实验」。)

## 2. 代码缺陷(建议修复)

1. **`server/notetable.py:32` — 潜伏 NameError(死代码雷)**:
   `freq_to_midi = lambda f: … math_log2(…)`,`math_log2` 从未定义,一旦被调用即抛
   `NameError: name 'math_log2' is not defined`(已实测复现)。当前仓库内无人调用它
   (`server/quantize.py` 使用自己的局部 `_freq_to_midi`),故不影响现有功能,但属必修隐患;
   同文件 `_log2` 亦为未使用死代码。建议:删除 `freq_to_midi`/`_log2`,或改用已导入的 `math.log2`。
2. **`server/quantize.py`(~L193-196)— O(n²) 性能**:量化主循环内对每个事件用
   `for h in holes` 重新收集"同拍已占用列",事件数上万时会明显变慢。建议改为
   增量维护 `dict[int, set[int]]`(行 → 已用列)。
3. **`server/audio_io.py:20` — 顶层无条件 `import soundfile`**:miniaudio 被写成"可选",
   soundfile 却是硬依赖(且注释声称优先 miniaudio,与 `decode_audio_file` 实际顺序相反)。
   soundfile 缺失时整个模块 import 即失败,连 ffmpeg 兜底都到不了。建议把 soundfile
   也做成可选(try/except),并调整解码顺序注释。
4. **`server/engines/dsp_engine.py:70` — 未使用变量 `idx_by_freq`**:无害,顺手清理。
5. **无版本管理**:工程根目录没有 `.git`,建议 `git init` 后提交,防止改动丢失。

## 3. 体检通过项(可放心)

- `server/`、`tools/` 全部 `.py` 通过 `compileall` 语法检查。
- **纯标准库核心链路实测通过**:读 30 音表(30 列,最低 `C`(MIDI 48)…最高 `E3`(MIDI 88))
  → 合成音符事件 → `quantize_to_tape`(自动移调/冲突感知折叠/置信过滤)→ `Tape`
  → JSON / CSV / SVG 序列化,无第三方依赖亦可运行。
- 数据文件合法:`data/note_table_30note.json`、`data/project.json`(≈417KB)、
  `tools/media/gt_twinkle.json`、`tools/score_ref/xiaye_score.json` 均可正常解析;
  `data/sessions/` 9 个会话的 `src.mp3` + `mono.wav`(RIFF)齐全。
- 引擎资源齐全:`third_party/basic_pitch-0.4.0-*.whl`(758KB)与 `third_party/omnizart`
  (89.7MB,含 `music_piano-v2` 的 `saved_model.pb` + `variables` 权重)均在。
- 前后端 API 一致:前端 `web/js/app.js` 调用的全部端点均能在 `server/api.py` 找到;
  PNG 导出由前端 canvas 本地实现,后端仅需提供 json/csv/svg。

## 4. 未验证项(需装依赖后才能跑)

- 三个识别引擎的实际转录效果:Basic Pitch(需 `onnxruntime`)、Omnizart(需
  `tensorflow`/`tf-keras`)、DSP(需 `numpy`/`scipy`/`soundfile`)在本机均因缺依赖
  未做端到端验证(`tools/e2e_check.py` 待依赖就绪后执行:`python tools\e2e_check.py --engine dsp`)。
- `third_party/omnizart` 模型能否被 TF 正常加载(无 TF 环境无法确认,权重文件齐全)。

## 5. 功能与使用速查(完整说明见上方正文)

- 形态:本地 Web 应用(FastAPI 后端 + 原生 JS 前端),`run.bat` 或 `python -m server.main` 启动,
  浏览器访问 `http://127.0.0.1:8765`。
- 流程:① 导入音频(MP3/WAV/…,miniaudio/ffmpeg 解码)→ ② 音符识别(Basic Pitch /
  Omnizart / DSP 引擎,或载入外部识别 JSON)→ ③ 编曲映射(30 音量化:折叠/夹取/丢弃、
  自动整曲移调、鲁棒移调、音域过滤、鬼影抑制、过近合并)→ ④ 纸带可视化编辑
  (30 音轨 × 时间步网格,点击加/删孔、拖拽擦除、空格试听)→ ⑤ 导出 JSON/CSV/SVG/PNG。
- 纸带数据模型:`row`=时间步(`步距 = 60/(BPM×每拍格数)` 秒),`col`=0..29 音轨,一行多列=和弦;
  一个孔 = 一次拨弦,音长靠孔间距表达。导出 JSON 含 `machine` 占位参数,供下一阶段
  G-code → GRBL 打孔使用(当前版本仅预留)。

---

# 🖥️ 运行环境矩阵 / 适配记录(2026-09 本机适配后)

> ⚠️ **本文档面向"后续会在多台电脑上继续开发"这一前提编写**:每一台机器环境不同,
> 请**先按下面的矩阵确认你所在的环境**,再执行对应命令,避免在错误环境跑出错误结果。
> 上方「⚠️ 当前存在问题(工程体检结论)」章节描述的是**体检当时(适配前)**的现状;
> 本节是**适配之后的最新状态**,两者并不矛盾,按时间先后阅读。

## 环境 A — 本机(已适配完成, 可直接运行)

| 项 | 值 |
|---|---|
| 机器 | Windows(桌面机);显卡 GTX 1050(实际支持 CUDA, Pascal CC 6.1, 但较老, 见 GPU 方案) |
| Python | **3.13.2**(仅此一版);工程内虚拟环境 **`.venv\`** |
| 依赖 | 已按 requirements.txt + basic_pitch wheel 全部装入 `.venv`(见下方实测版本) |
| 启动 | 双击 `run.bat`(已改为**优先使用 `.venv`**),或 `.venv\Scripts\python.exe -m server.main` |
| GPU 方案 | **CPU 推理即可**:Basic Pitch(ONNX)识别 27s 音频仅 ~1.4s;无需 CUDA/DirectML |

**实测安装的关键版本**(2026-09):fastapi 0.141.1 · uvicorn 0.52.4 · numpy 2.5.3 ·
scipy 1.18.1 · librosa 1.0.0 · onnxruntime 1.29.0 · basic-pitch 0.4.0 ·
**setuptools 80.10.2(必须 <81)** · soundfile 0.14.0 · miniaudio 1.71。

**本机网络特性**:pypi.org / github.com **不可直连**(连接被重置),需用国内镜像。
安装命令(在本工程根目录, 其他电脑同样适用):
```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python -m pip install third_party\basic_pitch-0.4.0-py2.py3-none-any.whl --no-deps
```
> 镜像备选: `https://mirrors.aliyun.com/pypi/simple/`、`https://mirrors.cloud.tencent.com/pypi/simple/`;
> 能直连 pypi.org 的网络可去掉 `-i` 参数。

**本机实测通过**(verification 记录):
- `tools\e2e_check.py --engine all`(mp3 解码 → Basic Pitch 107 音符/1.4s、DSP 167 音符
  → 30音量化 → JSON/CSV/SVG 导出)全部 OK;
- 服务器 HTTP 全链路: `/api/audio` 上传 → `/api/transcribe`(job 轮询)→ `/api/quantize`
  (78 孔)→ `/api/export/csv` 200 ✓;`/api/health` `{ok:true}`;首页静态资源正常;
- 唯一非功能失败:在 GBK 控制台打印 "✅" 报 UnicodeEncodeError —— 控制台编码问题,
  `run.bat` 已设 `PYTHONIOENCODING=utf-8`,正常使用不受影响。

> ⚠️ **Omnizart 引擎(改用 HTTP 服务形态, 不再误导性 ✓)**:GUI 里的 `Omnizart` 现在
> 是一个**可由 HTTP 引擎服务启用的可选引擎**——本机后端不再本机 import TensorFlow。它在
> `available_engines()` 里以服务可达性判断: 服务(见 deploy_server/SERVICE-INSTALL.md)在线且就绪才
> 可选;否则**置灰并给出原因**(服务不可达/模型缺失/没配地址),不会再假打勾。GUI ② 可填远程
> `http://IP:8766` 点“测试连接”启用。

## 环境 B — GPU 服务器(<server-ip>)

| 项 | 值 |
|---|---|
| 主机 | R730XD(Dell PowerEdge);**Windows Server 2022 Datacenter**, PowerShell 5.1 |
| 磁盘 | C: 893G(用 157G)/ D: 2.7T(用 1.3T)/ E: 465G |
| GPU | **NVIDIA RTX 2080 Ti(22GB 版, 22528 MiB)**,驱动 610.62,CUDA UMD 13.3,WDDM |
| Python | **未安装**(无 python/py/conda, 无 CUDA Toolkit/nvcc);工作全走容器(见下) |
| Docker | **Docker Desktop(WSL2 backend)+ nvidia runtime 已注册**;实测 `--gpus all` 容器能看到 2080 Ti 22G |
| 网络 | pypi.org 与清华镜像均可直连;**Docker 引擎代理**(HTTP_PROXY=服务器:7890,Clash)已持久写入用户级环境变量 |

**Omnizart 部署结论(已在服务器跑通: CPU 与 GPU 双路径均已真实转录验证)**
- Omnizart(music_piano-v2,TF+Keras2)因本机装现代 TF 障碍,已放到**服务器 Docker 容器**里跑;
  配方 = `python3.12 + tensorflow(-cpu 2.16.2) + tf-keras 2.16 + numpy 1.26.4 + scipy 1.13.1 + librosa 0.10.2`
  (TF2.16 强制 numpy<2.1,故 librosa 须退回 0.10),详见 `deploy_server/README.md` + `Dockerfile`。
- **CPU 容器已跑通**:27s twinkle → 168 音符(MIDI+events.json),产物
  `tools/score_ref/omnizart_server_cpu_twinkle.json`。
- **GPU 两方已验证**(大表见下方「GPU 加速结论」)*请勿只拉官方 *-gpu* 镜像就以为有 GPU*——
  需 Docker Desktop 引擎在线 + 用 `tensorflow[and-cuda]` 轮子补 CUDA/cuDNN。实测 168 音符与 CPU逐音符一致。
- **本机一条命令对接**:`tools/omnizart_remote.py`(设置 `OMNI_PASS` 等环境变量后)负责
  上传 wav →(缺镜像才构建)→ 容器转录 → 拉回 events.JSON,接入现有"识别 JSON 载入"流程;
  `--gpu` 走已配好的 GPU 容器。

**GPU 加速记录(RTX 2080 Ti 容器, 结论: 加速真实、结果无损)**
| 运行 | 转录耗时 s | 168 音符一致性 |
|---|---|---|
| CPU(Docker) | 149.5 | 基准 |
| GPU(2080 Ti) | **83.1** | 与 CPU **逐音符序列完全相同** |
GPU 的 83s 含模型加载+首步 cuDNN 初始化 ~9s 与 CPU 端特征提取;纯 U-Net 推理降到 ~0.1s/步。
产物: `tools/score_ref/omnizart_server_gpu_twinkle.json`。复现步骤见 `deploy_server/README.md` §4。

**环境 B 其它 GPU 引擎路线**(用于后续 Basic Pitch/源分离):onnxruntime-directml 最省事;
Demucs 用 torch cu12x 轮子自带 CUDA;2022+ 的 Windows 引擎走容器最稳。

## 其它电脑注意事项(兼容性, 防止误跑)

1. **Python 版本**:实测 3.13 可跑;3.11/3.12 亦预期兼容(本工程最初在 3.12 开发)。
2. **setuptools 必须 <81**:basic_pitch 0.4.0 运行时 `import pkg_resources`,而
   setuptools ≥81(尤其新版 84)**已删除 pkg_resources**,不钉版本会直接
   `ModuleNotFoundError: pkg_resources`(requirements.txt 已加入 `setuptools<81`)。
3. **网络**:pypi.org 直连不通的机器请加 `-i` 镜像(见上);能直连的不要加。
4. **numpy 2.x**:实测 numpy 2.5.3 + 全链路 OK(无需退回 1.x)。
5. **不要选的引擎**:TF 未装的机器上 GUI 的 Omnizart 徽标虽为 ✓,实际不可用(见上缺陷说明)。
6. **运行**:优先用工程内 `.venv` + `run.bat`;不要在系统 Python 里散装依赖(污染其它项目)。

## 适配修改状态清单(相对体检前)

- ✅ `run.bat` — 改为**优先调用 `.venv\Scripts\python.exe`**,找不到再退回 PATH python,
  最后才是旧 Python312 绝对路径(已修改)。
- ✅ `requirements.txt` — 追加 `setuptools<81`(含原因注释, 已修改)。
- ✅ `.gitignore` — 新增(忽略 `.venv/`、`.tmp/`、`__pycache__/`、`data/sessions/` 等)。
- ✅ `.venv\` — 本机新建(约 55+ 包);**不入库**,其它电脑按上节命令自建。
- ✅ `README.md` — 追加本"运行环境矩阵/适配记录"章节(已修改)。
- ✅ `deploy_server/` — 新增(Dockerfile + omnizart_transcribe.py + README):把 Omnizart 做成
  可在服务器(Docker,本机无关)运行的容器;CPU 与 **GPU** 配方均已在 2080 Ti 上实际验证
