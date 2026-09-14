# 安装并暴露 Omnizart 引擎为可按 IP:port 调用的 HTTP 服务

目的: 把 Omnizart(music_piano-v2)装到一台**能跑它的机器**(如带 Docker 的主机/带 GPU 的服务器),
放出 HTTP 端口。这样其它电脑上的上位机 GUI ② 填入 `http://<该机IP>:8766`, 就能把它当可选识别引擎
调用, 调用方电脑**不需要装 TensorFlow**。

文档定位: 可在与仓库无关的机器上, 仅凭本文(参照本目录源码 `omni_http.py`)完成部署。

---

## 0. 协议约定(调用方按此拼)

- `GET /health`
  200 json:
  ```json
  {"ok": true, "available": true, "model": "music_piano-v2", "device": "cpu|gpu", "reason": ""}
  ```
  `available=false` 的 `reason` 说明为何暂不可用(如模型缺失/TF 加载失败)。
- `POST /transcribe`  (multipart)
  字段: `file`=音频(wav 或 mp3 转 wav)、`ckpt`=music_piano-v2(可省)
  200 → **events 数组**, 每项含 `start_s, dur_s, freq, midi, velocity, confidence`(与 GUI /api/notes 兼容)。

---

## 1. 供给: 仓库自带引擎服务脚本

`deploy_server/omni_http.py` —— FastAPI 服务, lazy import omnizart+tf_keras, 暴露上述两端。
它需要一台"能跑 Omnizart"的 python(3.11 或 3.12)+ tensorflow*tf_keras+omnizart 包 的环境,
`omnizart` 包路径通过环境变量 `OMNI_PKG_PARENT`(其父目录需含 `omnizart/`)或本仓库 `third_party`
自动寻找。

### A. 用 Docker 起(自包含、调用方零 TF;占体积小, 无 GPU 也能 CPU)
先在仓库根有可使用的基础环境构建 CPU 镜像并启动 HTTP 包装(把 omni_http.py 卷进去即可):
```bash
# 1) 已有(或先 docker build 出)一个可跑 Omnizart 的镜像, 例如本仓库 deploy_server/Dockerfile -> omnizart:server
docker build -f deploy_server/Dockerfile -t omnizart:server .
# 2) 用该镜像再包一层常驻 HTTP 服务(挂 omni_http.py + 让 PYTHONPATH 找到 omnizart 包)
docker run -d --name omnizart-http -p 8766:8766 \
  -e OMNI_PKG_PARENT=/srv \
  -v "$PWD/deploy_server/omni_http.py":/svc/omni_http.py \
  omnizart:server bash -lc "pip install -q fastapi uvicorn python-multipart && python /svc/omni_http.py --port 8766"
# 3) 验证
curl http://127.0.0.1:8766/health
```
> `omnizart:server` 镜像已在容器内把 `omnizart` 放到 `/srv/omnizart`, 故 `OMNI_PKG_PARENT=/srv`,
> `omni_http.py` 父目录 `/svc` 进 `PYTHONPATH` 由 bash 内联执行保证。

- 若你的目标机没有上面镜像而有「能跑 Omnizart」的其它镜像/环境, 则仅需在其内额外
  `pip install fastapi uvicorn python-multipart` 并把本文件(或仓库 `third_party` 在 `/tp`)执行:
  `python omni_http.py --port 8766`(设 `OMNI_PKG_PARENT`/把 `third_party` 放对即可)。

### B. GPU 加速(可选)
同一 `omni_http.py` 无需改动; 换成一个能看到 GPU 的环境即可(见工程 README 环境 B §GPU:用
`tensorflow[and-cuda]` 轮子, 并设 `LD_LIBRARY_PATH` 指向 `site-packages/nvidia/*/lib` 及 `/usr/lib/wsl/lib`)。
启动后 `/health` 里 `device` 会返回 `gpu`。

---

## 2. 在 GUI 上位机上使用远程 Omnizart

1. 保证上位机后端能访问该端口(网络通; 跨容器/跨网段见你拓扑)。
2. GUI ② 的「Omnizart 服务地址」填 `http://<主机IP>:8766`, 点“测试连接”。
   后端 `/api/engines/omnizart/config` 会做真实探测:
   - 可达且模型就绪 → `device` 可见(如 gpu), Omnizart 进入可选列表(✓);
   - 不可达/模型缺 → 它保持 **✗ 不可用 + 给出原因**, 不会误打勾, 也不会让 transcribe 误用本地 TF。
3. 导入音频 → 若 Omnizart 可选, 下拉里选择它并开始识别; 服务端转录完 events 返回后自动进 ③ 编曲。

调用方后端逻辑(已实现): omni 通过已配置 URL 的 `/transcribe` 上传 wav 获得 events,
本地不 import TensorFlow。

---

## 3. 可离线携带的 tar(给“有 Docker、想离线跑”的机器)

本工程根目录已有一份可移植 CPU 镜像 tar(已生成, 本回导出于 2080Ti 服务器, 内含模型+python+TF+fastapi+HTTP 服务):
- 文件: `omnizart-server-cpu.tar` (约1.04 GiB)
- SHA256: `2F90F434079C75E4881E7B9BD3677741A12A2084E737B5BB10C1E93FA95680D6`

在另一台有 Docker 的机器上载入:
```bash
docker load -i omnizart-server-cpu.tar     # -> 标签 docker.io/library/omnizart:server
# 直接起 HTTP 服务(供本上位机 GUI 或其它机按 IP:port 调用)
docker run -d -p 8766:8766 --name omnizart-http omnizart:server
curl http://127.0.0.1:8766/health   # {"ok":true,"available":true,device:cpu,…}
# 一次性 CLI 转录
docker run --rm -v "$PWD/work":/data omnizart:server python /srv/omnizart_transcribe.py /data/x.wav --out /data/x.events.json
```

> 这是 CPU 版(无 GPU 也能跑,只是慢)。若要 GPU 版 tar(体积≈十几 GB),本会话当时未一并导出;需要时在服务器对已配好的 GPU 环境另行 `docker save`(见 deploy_server/README §4)。

也可自行从源码重建等价镜像: 在仓库根 `docker build -f deploy_server/Dockerfile.portable -t omnizart:server .`(联网装依赖)。

---

## 4. 常见原因提示(会出现在 GUI 的 reason 里)

- “服务不可达(http://IP:8766/health): …”→ 端口没起/网络不通/防火墙。
- “服务返回不可用: …”→ 引擎侧 TF 没装好或 checkpoint 缺失(看服务端日志)。
- GUI 若不配置服务地址, Omnizart 默认探测 `http://127.0.0.1:8766`(本机服务)。
