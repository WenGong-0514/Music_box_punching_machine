#!/usr/bin/env python3
"""Omnizart 远程转录 CLI —— 连接 GPU 服务器跑 Omnizart 并把 events.json 拉回本机.

设计动机
--------
Omnizart(music_piano-v2) 是 TensorFlow/Keras2 模型, 本机(py3.13/Win)装 TF+keras2 兼容极差,
因此让它在装有 RTX 2080 Ti 的服务器(环境 B)的 Docker 容器里跑。

对接方式
--------
本脚本产出与 tools/omnizart_run.py 一致的 {audio, engine, ckpt, events[]} JSON——
即工程"识别结果"中间格式: GUI ②「载入识别 JSON」导入; 或 tools/compare_to_score.py / eval 复用。

依赖: 需 paramiko (pip install paramiko).
凭证: 一律从环境变量读(不写死在代码里)—— OMNI_HOST / OMNI_USER / OMNI_PASS (或 OMNI_SSH_KEY)
示例(PowerShell, 服务器镜像已在且 Docker 引擎在线):
    $env:OMNI_PASS='...'; python tools/omnizart_remote.py "某曲.wav" --out result.json
    # 若需 GPU, 给 --gpus(命令里自动加); 自定义服务器改 OMNI_HOST 各变量即可。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OMNI_PKG_PARENT = ROOT / "third_party"   # 内含 omnizart 包
REMOTE_WORK = "D:\\omnizart_ws_remote"


# ------------------------------------------------------------------ helpers
def _ssh_module():
    try:
        import paramiko  # type: ignore
        return paramiko
    except Exception:  # pragma: no cover
        raise SystemExit("需要 paramiko: 请在命令行 `pip install paramiko`")


def _connect(pm):
    host = os.environ.get("OMNI_HOST", "")
    user = os.environ.get("OMNI_USER", "Administrator")
    pwd = os.environ.get("OMNI_PASS")
    key = os.environ.get("OMNI_SSH_KEY")
    if not host:
        raise SystemExit("[!] 未设置 OMNI_HOST(例如 $env:OMNI_HOST='192.0.2.10')。")
    if not pwd and not key:
        raise SystemExit("[!] 缺少凭证: 请设 OMNI_PASS 或 OMNI_SSH_KEY。")
    c = pm.SSHClient()
    c.set_missing_host_key_policy(pm.AutoAddPolicy())
    kw = dict(hostname=host, port=22, username=user, timeout=20,
              allow_agent=False, look_for_keys=False)
    if key:
        c.connect(**kw, key_filename=key)
    else:
        c.connect(**kw, password=pwd)
    return c, host


def _run(c, cmd, timeout=3600):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    o, e = out.read(), err.read()
    rc = out.channel.recv_exit_status()
    dec = lambda b: b.decode("utf-8", "replace")
    return rc, dec(o), dec(e)


# ------------------------------------------------------------------ build image (一次性)
def _ensure_image(c, pm, image: str) -> None:
    rc, o, e = _run(c, "docker image inspect {i} --format ok 2>nul".format(i=image), 60)
    if o.strip() == "ok":
        print("服务器镜像就绪:", image)
        return
    print("服务器无镜像 %s, 正在构建(需 Docker Desktop 引擎在线; 一次后复用)…" % image)
    ctx = Path(tempfile.mkdtemp(prefix="omni_ctx_"))
    tgz = ctx / "ctx.tar.gz"
    three = OMNI_PKG_PARENT / "omnizart"
    dep = ROOT / "deploy_server"
    with tarfile.open(tgz, "w:gz") as t:
        # 布局与仓库根一致: third_party/omnizart + deploy_server/{Dockerfile,omnizart_transcribe.py}
        t.add(str(three), arcname="third_party/omnizart", recursive=True)
        t.add(str(dep / "Dockerfile"), arcname="deploy_server/Dockerfile")
        t.add(str(dep / "omnizart_transcribe.py"), arcname="deploy_server/omnizart_transcribe.py")
    work = "D:\\omnizart_build"
    with c.open_sftp() as s:
        for d in (work,):
            try:
                s.stat(d)
            except Exception:
                s.mkdir(d)
        s.put(str(tgz), work + r"\ctx.tar.gz")
    ps = (
        "powershell -NoProfile -Command \""
        "$w='{w}'; Remove-Item -Recurse -Force $w\\root -ErrorAction SilentlyContinue; "
        "New-Item -ItemType Directory -Force -Path $w\\root\\deploy_server | Out-Null; "
        "tar -xzf $w\\ctx.tar.gz -C $w\\root; "
        "docker build -t {img} -f $w\\root\\deploy_server\\Dockerfile $w\\root"
        "\""
    ).format(w=work, img=image)
    rc, o, e = _run(c, ps, 2400)
    print(o[-1600:] if o else "")
    if e:
        print("[build-err]", e[-400:])
    if rc != 0:
        raise SystemExit("镜像构建失败(rc %d)—— 请确认服务器 Docker Desktop 已启动。" % rc)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("wav", help="本地音频(建议 wav; 非 wav 也可由容器解码)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--ckpt", default="music_piano-v2")
    ap.add_argument("--image", default="omnizart:server")
    ap.add_argument("--gpu", action="store_true", help="加 --gpus all(需 GPU 镜像与 NVIDIA 运行时)")
    args = ap.parse_args()

    p = Path(args.wav)
    if not p.exists():
        print("本地 wav 不存在:", p)
        return 2
    out_local = Path(args.out) if args.out else p.with_suffix(p.suffix + ".events.json")

    pm = _ssh_module()
    c, host = _connect(pm)
    print("connected:", host)

    _ensure_image(c, pm, args.image)

    with c.open_sftp() as s:
        try:
            s.stat(REMOTE_WORK)
        except Exception:
            s.mkdir(REMOTE_WORK)
        s.put(str(p), REMOTE_WORK + "\\in.wav")
    print("已上传:", p)

    out_remote = REMOTE_WORK + "\\events.json"
    _run(c, "del {f} 2>nul".format(f=out_remote), 60)
    gpu_flag = "--gpus all " if args.gpu else ""
    cmd = ("docker run --rm {gpu}-v {work}:/data {img} "
           "/srv/omnizart_transcribe.py /data/in.wav --out /data/events.json --ckpt {ckpt}"
           ).format(gpu=gpu_flag, work=REMOTE_WORK, img=args.image, ckpt=args.ckpt)
    print("转录中…")
    rc, o, e = _run(c, cmd, 3600)
    print(o[-2000:] if o else "")
    if e:
        print("[remote-err]", e.splitlines()[-2:])
    if rc != 0:
        print("转录失败 rc", rc)
        c.close()
        return 1

    with c.open_sftp() as s:
        s.get(out_remote, str(out_local))
    print("已保存本机:", out_local)
    d = json.load(open(out_local, encoding="utf-8"))
    print("音符数:", len(d.get("events", [])), "| 服务器耗时(秒):", d.get("elapsed_s"))
    print("对接: GUI ②「载入识别 JSON」导入, 或交 tools/compare_to_score.py 评估。")
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
