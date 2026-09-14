# Omnizart 服务器容器部署(示例: 一台带 RTX 2080 Ti 的 GPU 服务器)

Omnizart(music_piano-v2)是 TensorFlow + **Keras2** 模型,本机(Windows/py3.13)要跑现代 TF 还强依赖
Keras2 兼容极麻烦。工程因此把 Omnizart 放到带 **RTX 2080 Ti(22G)** 的 GPU 服务器上用 **Docker**
跑:引擎/权重都来自本工程 `third_party/omnizart`,平台无关地打包成容器镜像,任何机器调用同一套。

> ⚠️ **凭证**:服务器 SSH 密码等**不要写进这个文件**。调用方通过环境变量提供
> `OMNI_HOST / OMNI_USER / OMNI_PASS`(或 `OMNI_SSH_KEY`)。见下「如何调用」。

## 1. 服务器前置(一次性, 需在服务器上执行)

这台服务器现状(实测):
- **Win Server 2022** + **Docker Desktop**(WSL2)+ Docker **`nvidia` runtime 已注册**;
  `docker run --gpus all nvidia/cuda:12.4.1-base-ubi9 nvidia-smi` → 能见
  `RTX 2080 Ti, 22528 MiB`(已验证)。
- 服务器**本身未装 Python**;以下都走容器。

启用引擎唯一要的: **Docker Desktop 在运行**(GPU 拉镜在引擎层,故需手动点开,SSH 非交互会话拉不起来;引擎起来后常驻容器用 restart 策略会自行恢复)。

## 2. 一次构建镜像(CPU 版,已跑通)

在本机或服务器有仓库与 Docker 时执行(下面用本机仓库构建):

```bash
# 仓库根执行(上下文=仓库根)
docker build -t omnizart:server -f deploy_server/Dockerfile .
```

Dockerfile 锁定的依赖是**已验证可用组合**:
`python:3.12-slim + tensorflow-cpu 2.16.2 + tf-keras 2.16.0 + numpy 1.26.4 +
scipy 1.13.1 + librosa 0.10.2`(TF2.16 强制 numpy<2.1,故 librosa 得退回 0.10)。

## 3. 跑一次转录(容器)

任一台有仓库、能 docker 的机器(或服务器):

```bash
# 把 wav 放到一个目录, 挂到容器 /data
docker run --rm -v "/绝对路径/工作目录":/data omnizart:server \
    python /srv/omnizart_transcribe.py /data/曲.wav --out /data/曲.events.json
```

产物 `/data/曲.events.json` = `{audio, engine:'omnizart', ckpt, elapsed_s, events[]}`,
**与 tools/omnizart_run.py / GUI「载入识别 JSON」兼容**(events 项带 start_s,dur_s,freq, …)。

## 4. GPU 版(RTX 2080 Ti 实测可用)

> ⚠️ **别直接用官方 `tensorflow/*-gpu` 镜像就以为有 GPU**:该镜像要 NVIDIA Container Toolkit
> 注入 CUDA/cuDNN 到 `/usr/local/nvidia`,但 **Docker Desktop/WSL2 只注入 libcuda(驱动)**,
> 于是 TF 报 `Cannot dlopen GPU libraries … Skipping registering GPU devices`,**静默回退 CPU**。
> 实测解法 = 用 pip 的 `tensorflow[and-cuda]` 轮子(自带 CUDA12.x/cuDNN9.x)并设置 LD_LIBRARY_PATH。

**实测列明步骤(已在带 RTX 2080 Ti 的服务器上验证通过)**:
```bash
# 1) 可用官方 2.18.0-gpu 图做 python3.11 基础, 建立持 gpu 容器(挂工作目录)
docker pull tensorflow/tensorflow:2.18.0-gpu                 # 大(约11GB), 需代理/耐心
docker run -d --name omni-gpu --gpus all \
    -v /绝对路径/omnizart_ws:/work tensorflow/tensorflow:2.18.0-gpu sleep 86400
# 2) 容器内装组合依赖(国内镜像提速)
docker exec omni-gpu python -m pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    "numpy==1.26.4" "scipy==1.13.1" "numba==0.59.1" "llvmlite==0.42.0" \
    "librosa==0.10.2" "soundfile==0.12.1" "pyyaml" "pretty-midi" "mido" "jsonschema" pillow
# 3) 用 and-cuda 重装 TF (补齐 CUDA/cuDNN;有 ~1.7GB 轮子, 走镜像)
docker exec omni-gpu python -m pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    "tf-keras==2.18.0" "tensorflow[and-cuda]==2.18.0"
# 4) 跑转录(务必设 LD_LIBRARY_PATH 含 nvidia 轮子 lib + /usr/lib/wsl/lib 宿主驱动)
LD=$(docker exec omni-gpu sh -lc "ls -d /usr/local/lib/python3.11/dist-packages/nvidia/*/lib | tr '\n' ':'")
docker exec --env LD_LIBRARY_PATH="$LD:/usr/local/nvidia/lib:/usr/local/nvidia/lib64:/usr/lib/wsl/lib" \
    omni-gpu python /work/omnizart_transcribe.py /work/test.wav --out /work/gpu_out.json
```

**验证命中(确认真 GPU, 非 CPU 回退)**:
```bash
docker exec omni-gpu python -c \
  "import tensorflow as tf;print([d.name for d in tf.config.list_physical_devices('GPU')])"
# → ['/device:GPU:0']  (name: RTX 2080 Ti, 20258 MiB, compute capability 7.5, cuDNN version 90300)
```

**实测结论(twinkle 27s wav, 168 音符)**:
| 运行 | 转录耗时 s | 结果 |
|---|---|---|
| CPU(Docker, python:3.12+TF2.16) | 149.5 | 168 音符 |
| **GPU(2080 Ti 容器)** | **83.1** | 168 音符,**逐音符序列与 CPU 完全一致** |

GPU 的 83s 里含加载+首步 cuDNN 初始化~9s 与 CPU 端特征提取;纯 U-Net 推理 5 段从 CPU 全段
~数十秒 降至 0.1s/步。加速真实、结果无损。

> GPU 容器是会话级的;本机 `tools/omnizart_remote.py --gpu` 依赖此已配好的容器/环境。

## 5. 从本机一条命令对接

工程提供 `tools/omnizart_remote.py`:负责 上传 wav →(若无镜像则构建)→ 容器转录 → 拉回 events.json。
用前只设环境变量(凭证不落盘):

```powershell
$env:OMNI_HOST='192.0.2.10'          # 你的引擎服务器地址(示例为文档保留网段)
$env:OMNI_USER='Administrator'
$env:OMNI_PASS='<你的口令>'          # 或用 $env:OMNI_SSH_KEY 指定私钥
python tools\omnizart_remote.py "曲.wav" --out result.json
# GPU: 加 --gpu(需已拉 GPU 镜像)
```

> 前提: 本机须能 `import paramiko`(系统常有,否则 `pip install paramiko`);服务器 Docker Desktop 在线。

## 内置验证记录(真实)
部署过程 CPU 容器实测(twinkle 27s wav):
- 事件 168 个,模型载入 ~5s,转录 ~150s(CPU),产物 `tools/score_ref/omnizart_server_cpu_twinkle.json`
  已下载回本工程,可作为对接样例。

## HTTP 引擎服务(让 GUI 可以直接远程/本地调用, 而非只能 CLI)

Omnizart 引擎现已封装成**HTTP 服务形态**(供上位机 GUI 当作可选识别引擎使用,调用机不需装 TF):
- 服务本体: `deploy_server/omni_http.py`(FastAPI; /health 报 available+device/reason, /transcribe multipart 收音频返回 events)。
- 安装/暴露为可按 IP:port 调用: 看 `deploy_server/SERVICE-INSTALL.md`(含 Docker/GPU 封装与验证命令)。
- GUI ② 有"Omnizart 服务地址 + 测试连接";默认 `http://127.0.0.1:8766`,远程填 `http://<IP>:8766`。
