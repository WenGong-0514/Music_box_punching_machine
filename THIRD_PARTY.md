# 第三方组件与许可说明(THIRD PARTY NOTICES)

本文件列出本仓库使用/包含的第三方内容及其许可,并说明**哪些内容被有意排除在仓库之外**。
各组件许可以**其官方仓库/发行说明为准**;若需正式分发请自行核对最新条款。

---

## 1. 本项目自身许可

本项目采用 **GNU General Public License v3.0(GPL-3.0)** —— 全文见仓库根目录 [`LICENSE`](LICENSE)。

这意味着:
- 你可以自由使用、修改、分发本软件(包括商用);
- 但**分发修改版/衍生作品时,必须以 GPL-3.0 开源**并提供源代码(强著佐权);
- 分发时须保留版权声明与许可文本,且**不提供任何担保**。

> 若你日后希望改为宽松许可(如 MIT)或允许闭源衍生,需要更换整个项目的许可,
> 并确认所有贡献者同意。若希望采用"GPL-3.0 或更高版本",可在 README/LICENSE 中改为
> `GPL-3.0-or-later` 的表述(当前按 GPL-3.0 处理)。

**与第三方许可的兼容性**:本项目包含的第三方件(MIT / Apache-2.0 / BSD / ISC,见 §2、§3)
均与 GPL-3.0 兼容,可一同以 GPL-3.0 分发;但这些第三方文件**仍受其原始许可约束**,
不会被本项目的 GPL 覆盖(例如 `third_party/basic_pitch-*.whl` 仍是 Apache-2.0 作品)。

---

## 2. 随仓库分发的第三方件

| 组件 | 位置 | 用途 | 许可(以官方为准) |
|---|---|---|---|
| **Omnizart**(Music-and-Culture-Technology-Lab) | `third_party/omnizart/`(含 `checkpoints/music/music_piano-v2` 权重,约 90MB) | 钢琴专用转录引擎(music_piano-v2) | MIT |
| **Basic Pitch**(Spotify) | `third_party/basic_pitch-0.4.0-py2.py3-none-any.whl`(含 `icassp_2022/nmp.onnx` 模型) | 多音高识别引擎(ONNX 运行时,免 TF) | Apache-2.0 |
| **合成测试音频** | `tools/media/twinkle_30note.*` | 冒烟测试 | 由本项目 `tools/make_test_audio.py` 合成生成(自有) |
| **社区转录 MIDI** | `out/Pachelbel_Canon_in_D.mid`(如保留) | 示例乐谱 | 作品为公有领域(*Canon in D*, J. Pachelbel, 卒于 1706);MIDI 转录来自 [bitmidi.com](https://bitmidi.com/pachelbel-mid) 用户上传 |

> 若你不希望仓库体积过大(主要来自 Omnizart 权重),可把 `third_party/omnizart/checkpoints/`
> 加入 `.gitignore`,并在此文件提供获取方式(例如从 Omnizart 官方 release 下载后放入)。

---

## 3. 通过包管理器安装的运行时依赖(不随仓库分发)

后端:FastAPI(MIT)、uvicorn(BSD-3)、python-multipart(Apache-2.0)、Pydantic(MIT)、
NumPy(BSD-3)、SciPy(BSD-3)、soundfile(BSD-3)、miniaudio(Python 绑定 MIT;底层 miniaudio 为 MIT-0/公有领域)、
librosa(ISC)、mir_eval(MIT)、pretty_midi(MIT)、mido(MIT)、resampy(ISC)、numba(BSD-2)、llvmlite(BSD-2)、
onnxruntime(MIT)、setuptools(<81, MIT)。完整与最新版本见 [`requirements.txt`](requirements.txt)。

前端:**零第三方 JS 依赖**(原生 ES Module + Canvas + WebAudio)。

---

## 4. 有意排除在仓库之外的内容(见 `.gitignore`)

以下内容涉及**体积**或**第三方版权**,默认不入库;如需在本地复现请自行准备:

| 内容 | 排除原因 | 本地获取方式 |
|---|---|---|
| `data/sessions/**`(导入音频与解码 wav) | 体积大、含个人音频 | 直接导入你自己的音频即可自动生成 |
| `data/project.json` | 自动存档,频繁变更且体积大 | 首次运行/量化后自动生成 |
| `out/**` | 生成物 + 可能含**商业录音** | 由 GUI ⑤ 导出或 `tools/make_preflight_gcode.py` 生成 |
| `omnizart-server-*.tar`(约 1GB 镜像) | 体积过大,不适合 Git | 用 `deploy_server/Dockerfile.portable` 自行构建 |
| `tools/media/stems/**`(Demucs 分轨 WAV) | 体积大,且派生自商业录音 | `python tools/source_separate.py <音频> --model htdemucs_6s` |
| `tools/score_ref/page*.svg`、`tools/score_ref/xiaye_score.json` | **第三方乐谱**(抓取自乐谱站,版权归原作者) | 仅用于本地个人学习对比;需要时自行获取 |
| `ncm_tools/**` | 与本项目无关的私人辅助工具(含第三方二进制) | 保留在本地,不随仓库分发 |

---

## 5. 外部软件(本项目推荐但不由本仓库分发)

| 软件 | 用途 | 许可/性质 |
|---|---|---|
| [MuseScore](https://musescore.org/) | 打开导出的 MIDI:看谱、播放、编辑 | 开源(GPL-3.0) |
| [Synthesia](https://www.synthesiagame.com/) | MIDI 钢琴跟弹练习(免费版有限制) | 商业软件(有免费版) |
| Docker Desktop / WSL2 | 在服务器上运行 Omnizart 引擎服务 | 商业/免费条款见官方 |

---

## 6. 引用与致谢

- 30 音纸带音表来源:[搜狐 DIY 教程](https://m.sohu.com/a/242873889_100214167/)、
  [MMDigest / Sankyo 30-note](https://www.mmdigest.com/archives/Digests/201201/2012.01.30.01.html)。
- 引擎与算法:Omnizart(music_piano-v2)、Spotify Basic Pitch、Demucs 源分离、librosa/scipy 等社区工具。
- 评测用参考谱面:*夏野与暗恋(C调版)* 抓取自 [piastudy.com](https://piastudy.com/Intermediate/baTNdKab),
  版权归原作者,仅供个人学习对比(未随仓库分发)。
