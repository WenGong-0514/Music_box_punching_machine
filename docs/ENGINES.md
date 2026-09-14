# 引擎评测与调优(开发参考)

> 从 README 迁入的历史评测与实验记录(内容保持原样, 仅对内网地址/用户名做了占位化)。
> 结论用于选型与调参; 复现脚本见 `tools/`。

---

## 高精度引擎与曲谱对比评估(《夏野与暗恋》实测)

**谱面参照**: 抓取并解析了 [PiaNoproblem/天天钢琴 夏野与暗恋(C调版)](https://piastudy.com/Intermediate/baTNdKab)
的 Verovio SVG 谱面(自带音高/时值数据, 74 小节 / 1007 音符, 右手旋律 446 + 左手伴奏 561),
保存为 `tools/score_ref/xiaye_score.json`(仅供个人学习对比, 版权归原作者)。

**实测结论**(mp3 `闫东炜 - 夏野与暗恋.mp3`, 164s):
- 速度对齐: 录音 ≈ **111 BPM**, 谱面时长 161s ≈ 音频 164s ✓
- 调性: 录音比 C调版谱**高 1 个半音**(音级直方相关 r≈0.93), 已自动做移调对比
- 与谱面逐音符命中率(时间对齐窗口内, 谱面音被识别到的比例):

| 引擎 | 右手旋律(446音) 严口径 | 右手 宽松(±八度) | 左手 宽松 |
|---|---|---|---|
| Basic Pitch(旧) | 8% | 52% | 33% |
| **Omnizart v2(新)** | **43%** | **54%** | 13% |

> 严口径 = ±~1/16拍 & ±1半音: 这是"旋律音高与起音时机都准"的度量, Omnizart 约为 BP 的 **5 倍**。
> 宽松口径允许 ±1 八度: BP 因输出 1860 个事件(大量八度鬼影/噪音)更容易"蒙中",
> 但精度低; Omnizart 只输出 1448 个干净钢琴音符。左手两类都不高, 因为
> C调版是**简化改编谱**, 其左手分解和弦织体与录音原伴奏并不逐音一致 —— 属谱-曲差异,
> 不是纯识别误差。

**怎么用**:
```bat
python tools\omnizart_run.py "闫东炜 - 夏野与暗恋.mp3" --ckpt music_piano-v2 --out tools\score_ref\omni_events.json
python tools\compare_to_score.py tools\score_ref\omni_events.json
```
GUI 里: 识别引擎选 **Omnizart** 直接跑; 或在②用「载入识别 JSON」导入 `omni_events.json`,
再量化成 30 音纸带。命令行产物格式与 GUI 内部一致。

**给八音盒的提醒**: 完整钢琴织体跨 ~5 个八度, 而 30 音八音盒只有 ~3 个八度(还有空音);
直接量化会把 40%+ 的音做"八度折叠"(实测 1448 → 1368 孔, 618 个折叠), 折叠过多会让旋律/和声挤在同一音域而失真。**面向八音盒, 建议后续做"编曲适配"**: 
提取主旋律 + 简化伴奏、整体移调到八音盒音域、舍弃超出音域的装饰音, 再量化。


## 进阶实验: GPU / 源分离 / 超音域处理

**显卡与 DirectML(实测 RX 6900 XT)**
- 已装并验证: `onnxruntime-directml 1.24.4`(`DmlExecutionProvider` 可用)、
  `torch-directml`(识别到 `AMD Radeon RX 6900 XT`)。
- Basic Pitch 的 ONNX 推理可走 DirectML(`device: dml` 参数), 该小模型加速有限(~10%)。
- **Demucs 4 分轨** `tools/source_separate.py`(默认 htdemucs): 复数 FFT 在 torch-directml
  上不支持(`ComplexFloat`), 目前 CPU 跑(164s 曲 ≈97s, 可用)。

**源分离对识别的影响(《夏野与暗恋》实测)**
Demucs 4分轨(htdemucs)与 6分轨(htdemucs_6s, 含独立 guitar/piano 声部)能量实测:
4s: drums 45.5% / bass 13.2% / other 41.3% / vocals 0%;
6s: drums 46.5% / bass 16.7% / **piano 31.6%** / other 4.1% / guitar 1.1% / vocals 0%。
说明该"钢琴曲"实际带打击乐、无演唱, 且 4s 的 other 里混有吉他等杂项。
用 Omnizart 分别转录后与 C调版谱对比:

| 转录输入 | 右手(旋律)命中 | 左手命中 | 音符数 | "突兀高音窗"数(每0.25s最高音>MIDI86) |
|---|---|---|---|---|
| 原曲整轨 | 54% | 13% | 1448 | 189 |
| other 单轨(4s) | 59% | 25% | 1401 | 125 |
| **纯钢琴轨(6s)** | **59%** | 20% | **1214** | **113** |

音区诊断(`tools/analyze_register.py`): 三种转录的"主旋律轨迹"中位数均 ≈77-79,
与谱面右手旋律(中位76, 范围60-91)一致 —— 主旋律本身并不偏低;
去掉鼓/贝斯后整体音区下限由 MIDI 35 → 53, 低音浑浊明显减少。
纯钢琴轨听感最干净(事件最少、突兀高音最少), 已作为当前 GUI 演示工程。

**结论与剩余限制**: "仅保留钢琴"通过 htdemucs_6s 的独立 piano 声部达成
(用法: `python tools\source_separate.py <音频> --model htdemucs_6s --stems piano --device cpu`)。
若仍觉"主旋律偏低/高音突兀", 主要来自 ①原曲钢琴本身音域极宽(旋律最高音达 MIDI 90+,
属谱面正常内容) ②30 音八音盒只有约 3 个八度且低音区音色发闷 —— 是"钢琴谱 vs 八音盒
编曲"的必然差异而非识别错误, 需下一步"编曲适配"(抽主旋律+简化伴奏+音域搬移)解决听感。

**超音域音符怎么处理(社区做法 + 我们的实现)**

调研结论([music-box 30音工具链](https://github.com/samuelchvez/midi-to-thirty-notes-music-box-sheet)、
[MusicBoxDesigner](https://github.com/BiologyHazard/MusicBoxDesigner)、
[Muro Box 改编教程](https://murobox.com/zh/20260225-musescore-tutorial-post-zh/)、
[musicboxmaniacs 移调曲例](https://musicboxmaniacs.com/explore/melody/see-you-again-5-semitones-down_160369/)、
[30音手摇纸带 DIY 文章](https://m.sohu.com/a/242873889_100214167/)的改编注意事项):
1. **整曲移调**是主流第一手段 —— 工具普遍提供 `-t` 转调; 社区谱名常直接标"下移 N 半音"。
2. 读孔机械对**同列过近的重复音会忽略**(相邻 1/4 拍内), 工具默认丢弃这类音。
3. 超出音域的装饰音/声部常被**直接去掉**, 而非机械地八度折叠(折叠会与同刻音撞车/失真)。
4. 面向八音盒的"编曲"范式 = 主旋律 + 简化伴奏, 宁可删层不硬塞。

对应已在量化器实现的改进(④/③ 界面可选):
- **自动整曲移调**(默认 ±24 半音搜索, `auto_transpose`): 选择让最多音符原位落在 30 音域内的调,
  实测《夏野与暗恋》最优 **-13 半音**, 八度折叠从 618 降至 372(-40%);
  去鼓分轨后再量化只需 **-1 半音、折叠仅 156**。
- **冲突感知折叠**(`fold` 策略升级): 折回时避开与同拍其它音同列。
- **鲁棒自动移调**(`shift_robust`, 默认开): 极高/极低"点缀音"(铃声/特效音, 移调后仍超音表
  1个八度+)几乎不参与移调评分, 并统计 `extreme_high/low`, 避免少数高音把整曲拖低。
- **音域过滤**(GUI ③可设 `音域上限/下限`): 直接丢弃超过指定 MIDI 的音再量化,
  实测纯钢琴轨去掉 >MIDI92 的 50 个点缀高音后八度折叠 133→83。
- 保留 `skip / clamp / min_gap_steps(过近丢弃)` 等原有策略。
- 评估脚本: `python tools\analyze_transpose.py` / `python tools\analyze_robust.py` /
  `python tools\analyze_filter.py` / `python tools\analyze_register.py`。

> 后续若做"自动八音盒编曲", 建议: 取主旋律+低音贝斯化+和弦块 → 整曲移调 → 逐音在
> [折叠/八度翻/去音] 间决策, 输出一首真正"像八音盒"的改编, 而不仅是全量压入。

## 开源钢琴扒谱引擎横向评测(本机实测)

在"6s 纯钢琴轨"上用同一口径(与 C调版谱对齐; 时间窗≈八分音符、音高±1半音或±1八度)对比:

| 引擎 | 音符数 | 右手(旋律)命中 | 左手命中 | "突兀高音窗" | 备注 |
|---|---|---|---|---|---|
| **Omnizart music_piano-v2** | 1214 | **59%** | 20% | **113** | 最干净、主旋律最准; 已被选为默认 |
| Basic Pitch (ICASSP2022) | 1490 | 53% | **30%** | 较多 | 左手(低音/八度)覆盖高但噪音大 |
| Bytedance piano-transcription (Note_pedal F1=0.9677) | 1855 | 37% | 10% | 252 | 需16kHz输入; 此曲上明显差于前两者 |
| DSP 频谱引擎 | — | 低 | 低 | — | 轻量兜底, 精度有限 |

合成已知真值集(72 音符, 未做鬼影抑制的原始事件口径)音符 F1: Basic Pitch 79.6% >
Omnizart 60.3% ≈ DSP 60.4%(Omnizart 在量化层鬼影抑制后大幅改善)。

**未跑通/结论**: Magenta Onsets&Frames 官方依赖钉死 numpy1.21 等, 与本机环境冲突;
MT3/aria-amt/muscriptor 等或依赖旧 TF、或需额外 GPU/网络下载, 未纳入本次对比。
**当前最佳组合**: Demucs htdemucs_6s 纯钢琴轨 → Omnizart music_piano-v2 → 鲁棒自动移调量化。
工具: `python tools\omnizart_run.py` / `python tools\bytedance_run.py` / `python tools\eval_pipeline.py`
评估: `tools\compare_to_score.py`(谱面对比)、`tools\analyze_register.py`(音区)、`tools\gt_eval.py`(合成真值)。

