# Omnizart 转录容器 (CPU 影像为默认; GPU 用法见 README)
# 基准与依赖为已在 RTX 2080 Ti 服务器上验证过的 CPU 组合:
#   python3.12 + tensorflow-cpu 2.16.2 + tf-keras 2.16 + numpy 1.26 + scipy 1.13 + librosa 0.10
# 说明: TF2.16 强制 numpy<2.1, 而新 librosa1.x 要 numpy>=2.1 -> 故钉教材兼容版。
# 生成:  docker build -t omnizart:server .
FROM python:3.12-slim

# 系统库(部分 wheel 需要, 低风险)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 先把带版本的三方依赖装上 (之后不再动, 避免与 TF 冲突)
COPY third_party/omnizart /srv/omnizart

WORKDIR /srv

# 固定版本组合 (RF 已验证)
RUN pip install --no-cache-dir \
        'numpy==1.26.4' \
        'scipy==1.13.1' \
        'numba==0.59.1' \
        'llvmlite==0.42.0' \
        'librosa==0.10.2' \
        'soundfile==0.12.1' \
        'h5py' 'pyyaml' 'pretty-midi' 'mido' 'six' 'jsonschema' pillow \
    && pip install --no-cache-dir \
        'tensorflow-cpu==2.16.2' \
        'tf-keras==2.16.0'

# 作业脚本
COPY deploy_server/omnizart_transcribe.py /srv/omnizart_transcribe.py
# omnizart 包位于 /srv/omnizart; 其父 /srv 加入 sys.path 即可 import
ENV PYTHONPATH=/srv \
    TF_CPP_MIN_LOG_LEVEL=3

ENTRYPOINT ["python", "/srv/omnizart_transcribe.py"]
