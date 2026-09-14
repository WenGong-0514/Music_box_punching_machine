#!/usr/bin/env python3
"""Omnizart(music_piano-v2) 转录工具 —— 在满足依赖的容器内以命令行运行.
参数:
    python omnizart_transcribe.py <input.wav> [--out out.json] [--ckpt music_piano-v2]
容器用法(需挂载本机 wav 到 /data, 见 deploy_server/README.md):
    docker run --rm -v "宿主工作目录":/data omnizart:server \
        python /srv/omnizart_transcribe.py /data/xxx.wav --out /data/xxx_events.json
输出 events.json 结构与 tools/omnizart_run.py 以及 GUI「载入识别 JSON」兼容。
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, '/srv')  # /srv/omnizart 的父目录

os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')


def load_app():
    import tensorflow as tf
    import tf_keras  # noqa
    tf.keras = tf_keras  # omni 老代码 tf.keras.* 需 keras2 (tf_keras)
    from omnizart.music.app import MusicTranscription
    return MusicTranscription()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('wav')
    ap.add_argument('--out', default=None)
    ap.add_argument('--ckpt', default='music_piano-v2')
    args = ap.parse_args()

    wav = args.wav
    if not os.path.isfile(wav):
        print('wav not found:', wav)
        return 2
    ckpt = '/srv/omnizart/checkpoints/music/' + args.ckpt
    if not os.path.isdir(ckpt):
        print('ckpt missing:', ckpt)
        return 2

    t0 = time.time()
    app = load_app()
    print('model-load %.0fs' % (time.time() - t0), flush=True)

    t1 = time.time()
    out_dir = '/srv/out'
    midi = app.transcribe(wav, model_path=ckpt, output=out_dir)
    dt = time.time() - t1
    print('transcribe %.0fs' % dt, flush=True)

    events = []
    for inst in midi.instruments:
        for n in inst.notes:
            events.append({
                'start_s': round(float(n.start), 4),
                'dur_s': round(max(0.01, float(n.end) - float(n.start)), 4),
                'freq': round(440.0 * 2 ** ((int(n.pitch) - 69) / 12.0), 2),
                'midi': int(n.pitch),
                'velocity': int(n.velocity),
                'program': int(inst.program),
            })
    events.sort(key=lambda e: e['start_s'])
    print('notes:', len(events), flush=True)

    if args.out:
        out = {'audio': wav, 'engine': 'omnizart', 'ckpt': args.ckpt,
               'elapsed_s': round(dt, 1), 'events': events}
        os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print('wrote', args.out, flush=True)
    elif events:
        print(json.dumps({'engine': 'omnizart', 'ckpt': args.ckpt,
                          'events': events}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
