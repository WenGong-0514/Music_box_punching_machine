# 🎼 MusicBox Tape Studio

**30 音纸带八音盒 · 打孔机上位机**
把音乐变成纸带孔位,并生成可直接驱动 GRBL 打孔机的 G-code。

本地 Web 应用(Python FastAPI 后端 + 浏览器原生 JS 前端,零构建依赖):
导入音频或乐谱 MIDI → 得到音符 → 量化到 30 音纸带 → 网格编辑 → 导出纸带/MIDI/图纸/**打孔 G-code**。

---

## 功能一览

- **两种输入方式**
  - **音频识别**:MP3/WAV/FLAC/OGG/M4A → 音符。内置 Basic Pitch(ONNX,快)、DSP 轻量引擎,以及可选的
    Omnizart 钢琴专用模型(经 HTTP 引擎服务调用,见下)。
  - **乐谱 MIDI 导入**:直接载入正确的 `.mid`,软件会列出各**乐器轨**(GM 音色 / 音符数 / 音域,
    鼓轨自动标灰),勾选一条或多条轨道 → 直接取谱面音符,**不再依赖从音频里猜音符**。
- **编曲量化**:自动整曲移调、冲突感知八度折叠、音域过滤、八度鬼影抑制、同列过近丢弃等策略,
  并提供完整统计(保留/折叠/丢弃/移调量…)。
- **纸带可视化编辑**:30 音轨 × 时间步网格;点击加删孔、拖拽擦除区域、空格试听(WebAudio 拨弦合成)。
- **导出**:JSON(工程数据)、CSV(孔位表)、SVG/PNG(图纸)、**MIDI**(给钢琴软件/DAW 演奏)、
  **G-code**(GRBL 打孔,含孔数/纸带长度/耗时预估注释)。
- **打孔路径规划**:同排多孔自动停带按 X 依次冲、每行从最近端进入、空行跳过、
  X/Y 移动保持在安全高度、结束自动多送 50mm 便于剪带。

---

## 快速开始

```bat
:: 1) 依赖(推荐用工程内虚拟环境; Windows + Python 3.13 已实测)
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

:: 2) Basic Pitch 引擎必须用仓库内 wheel 安装(原因见下)
.venv\Scripts\python -m pip install third_party\basic_pitch-0.4.0-py2.py3-none-any.whl --no-deps

:: 3) 启动
run.bat
```

然后浏览器打开 <http://127.0.0.1:8765>。

> **后端不运行 = 页面能打开但识别/下载全部失败**。`run.bat` 窗口关掉即等于关闭服务。

### 依赖安装要点

- **Basic Pitch 不要 `pip install basic-pitch`**:Windows + 新 Python 下它会强拉不兼容的 TensorFlow。
  本项目方案 = **仓库内 wheel + ONNX 运行时(免 TF)**:
  ```bat
  pip install third_party\basic_pitch-0.4.0-py2.py3-none-any.whl --no-deps
  pip install mir-eval pretty-midi "resampy<0.4.3" onnxruntime
  ```
- **`setuptools` 必须 < 81**:`basic_pitch` 运行时 `import pkg_resources`,而 setuptools ≥81 已移除该模块
  (`requirements.txt` 已固定)。
- 网络受限时加镜像:`-i https://pypi.tuna.tsinghua.edu.cn/simple`(可换阿里/腾讯镜像)。
- **Omnizart 引擎**不需要在本机装 TensorFlow:它由独立的 HTTP 引擎服务提供,
  部署见 [`deploy_server/SERVICE-INSTALL.md`](deploy_server/SERVICE-INSTALL.md);
  GUI ② 里填服务地址(`http://<ip>:8766`)→「测试连接」即可选用。服务不可达时该引擎会自动置灰并给出原因。

---

## 界面流程(五步)

1. **① 导入音频** — 拖入/选择音频,显示波形。
2. **② 音符识别** — 选择引擎,或用「载入识别 JSON」导入外部识别结果,
   或用「**载入 MIDI 乐谱…**」直接选乐器轨(推荐手上有正确乐谱时使用)。
3. **③ 编曲映射** — 设置 BPM、每拍格数、音域外策略(`折叠收进30音`/`夹到边界`/`丢弃`)、
   自动移调范围、音域上下限 → 生成纸带孔位。
4. **④ 纸带编辑预览** — 点击加/删孔、拖拽擦除、空格试听、`E` 切换工具、缩放/适应宽度。
5. **⑤ 导出** — JSON / CSV / SVG / PNG / **MIDI** / **G-code(GRBL)**。

快捷键:`Space` 播放/停止,`E` 切换编辑工具,滚轮 + `Ctrl` 缩放。

---

## 硬件:打孔机与 G-code

本项目的打孔输出已按实机参数实现(坐标系、纸带几何、Z 三层、路径规划、GRBL 配置、耗时模型):

- **X** = 纸带横向(音调),**X0 = 纸带左边缘线**且为**冲针圆心**(无半径补偿);X+ 向右。
- **Y** = 纸带纵向(时间),Y+ 向前;纸带名义速度 **8 mm/s**。
- **Z** = 冲针:`0` 最高位 / `6` 安全高度 / `10` 冲孔 → 单次冲孔行程 4mm。
- 纸带 70mm 宽,有效音频区 57.5mm,左右空白各 6.25mm;列分布 `X(col)=6.25+col×(57.5/29)`。
- 结束不回 Y0,而是继续前进 50mm 便于剪带。

👉 **完整规格、参数表、上机前校验流程与 GRBL 设置建议见 [docs/MACHINE.md](docs/MACHINE.md)**。

---

## 30 音音表(可替换)

内置标准 30 音纸表(两个独立来源印证):

```
第1列(最低) … 第30列(最高):
C  D  G  A  B | C1 D1 E1 F1 #F1 G1 #G1 A1 #A1 B1 | C2 #C2 D2 #D2 E2 F2 #F2 G2 #G2 A2 #A2 B2 | C3 D3 E3
```

- 低音区只有自然音;半音从 `E1` 起齐全;顶部 `C3 D3 E3` 为自然音。
- **音表必须与你的实际音梳一致**。不一致时改 `data/note_table_30note.json` 的 `columns`(30 项,升序);
  硬件列序相反就把数组倒序。`base_octave` 只影响试听音高与折叠,不影响孔位相对布局。

---

## 纸带数据模型

纸带八音盒的原理:**一个孔 = 一次拨弦**,音长由孔间距表达,孔本身不表音长。

```
row = 时间步(步距 = 60/(BPM×每拍格数) 秒)   col = 0..29 音轨(对应音表 30 列)
同一 row 多个 col = 和弦(同时打多孔)
```

---

## 目录结构

```
server/          FastAPI 后端(引擎、量化、纸带、MIDI 导入导出、G-code 生成)
web/             前端(原生 JS + Canvas + WebAudio, 零构建)
tools/           命令行工具: 合成测试音频、e2e 冒烟、评测、预校验 G-code 生成
deploy_server/   把 Omnizart 部署成 HTTP 引擎服务(容器 / 安装文档 / GPU 复现)
data/            音表配置(note_table_30note.json)与自动存档(project.json, 已忽略)
docs/            开发者文档与参考(MACHINE / DEVELOPMENT / ENGINES / HISTORY)
```

---

## 文档

| 文档 | 内容 |
|---|---|
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | **开发者主文档**:架构、模块职责、数据结构、API 清单、扩展指南、技术债、路线图 |
| [docs/MACHINE.md](docs/MACHINE.md) | 打孔机坐标与 G-code 规格、参数表、上机校验、GRBL 配置、耗时模型 |
| [docs/ENGINES.md](docs/ENGINES.md) | 引擎选型与调优实测(Basic Pitch / Omnizart / ByteDance / DSP、Demucs 源分离、移调实验) |
| [docs/HISTORY.md](docs/HISTORY.md) | 多机环境适配与变更记录(历史) |
| [deploy_server/SERVICE-INSTALL.md](deploy_server/SERVICE-INSTALL.md) | 用 Docker 把 Omnizart 装成可按 IP:port 调用的引擎服务 |
| [THIRD_PARTY.md](THIRD_PARTY.md) | 第三方组件许可 + 被排除内容说明 |

---

## 测试 / 验证

```bat
python tools\make_test_audio.py                 :: 生成合成测试音频(含超音域片段)
python tools\e2e_check.py --engine all          :: 冒烟: 音频→识别→量化→导出
python tools\make_preflight_gcode.py            :: 生成上机前"两孔/边界"预校验 G-code
python tools\compare_to_score.py x.json         :: 与参考谱面逐音符对比
```

Windows 控制台默认 GBK,打印 emoji 可能报 `UnicodeEncodeError`;用 `set PYTHONIOENCODING=utf-8`
(`run.bat` 已设)即可,属控制台编码问题而非逻辑错误。

---

## 已知限制 / 技术债

- 尚无 GRBL **串口直连**(连接/流式发送/暂停/急停)——G-code 目前以文件下载方式提供。
- 长曲目(如 2.8m、约 30 分钟)尚未支持**分段/断点续打**。
- 若干小缺陷待修(`notetable.freq_to_midi` 死代码、`quantize` 的 O(n²) 收集等),
  详见 [docs/DEVELOPMENT.md §9](docs/DEVELOPMENT.md)。
- 音频识别精度受音源影响大;手上有正确乐谱时,优先用「MIDI 乐谱导入」而不是音频识别。

---

## 许可与致谢

- 本项目采用 **GNU General Public License v3.0**(GPL-3.0),全文见 [`LICENSE`](LICENSE)。
  第三方组件仍遵循其各自许可(MIT / Apache-2.0 / BSD / ISC),详见 [THIRD_PARTY.md](THIRD_PARTY.md)。
- 被有意排除在仓库外的版权内容(商业录音、第三方乐谱等)也一并列在 [THIRD_PARTY.md](THIRD_PARTY.md)。
- 特别感谢 Omnizart、Spotify Basic Pitch、Demucs、librosa 等开源项目,
  以及 30 音纸带音表的社区资料([搜狐 DIY 教程](https://m.sohu.com/a/242873889_100214167/)、
  [MMDigest / Sankyo 30-note](https://www.mmdigest.com/archives/Digests/201201/2012.01.30.01.html))。
