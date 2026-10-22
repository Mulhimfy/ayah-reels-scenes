"""Encode one part of publish/new_scenes.json the way the v1 library was
encoded (AyahReel's tool/curate_scenes.py), for the v2 (stills) and v3
(clips) releases, and make each scene's poster for the app.

    python publish/encode.py <part> <parts>

  out/v2/<id>.jpg     still, cover-cropped to 1080x1920 (1920x1080 wide),
                      JPEG q90
  out/v3/<id>.mp4     clip: the first 12 s, video only, 30 fps, H.264
                      CRF 23 capped at 2.5 Mbps, faststart
  out/meta/posters/<id>.webp   216x384 (384x216 wide) poster, WebP q70
  out/meta/part-<n>.json       {id: {"bytes": n} | {"error": "..."}}
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

from PIL import Image

part, parts = int(sys.argv[1]), int(sys.argv[2])
UA = 'AyahReel scene publisher (https://github.com/Mulhimfy/ayah-reels-scenes)'
for d in ('out/v2', 'out/v3', 'out/meta/posters', 'tmp'):
    os.makedirs(d, exist_ok=True)


def cover(img, size):
    w, h = size
    s = max(w / img.width, h / img.height)
    img = img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))),
                     Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def fetch(url, dest):
    for i in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, 'wb') as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
            if os.path.getsize(dest) > 1000:
                return
        except Exception as e:  # noqa: BLE001
            err = e
        time.sleep(5 * (i + 1))
    raise RuntimeError(f'download failed: {err}')


def poster(img, wide, dest):
    cover(img.convert('RGB'), (384, 216) if wide else (216, 384)).save(
        dest, 'WEBP', quality=70, method=6)


scenes = json.load(open('publish/new_scenes.json', encoding='utf-8'))
mine = [s for i, s in enumerate(scenes) if i % parts == part]
done = {}
for s in mine:
    sid, wide = s['id'], s['wide']
    w, h = (1920, 1080) if wide else (1080, 1920)
    src = os.path.join('tmp', sid + '.src')
    try:
        fetch(s['media_url'], src)
        if not s['video']:
            dest = f'out/v2/{sid}.jpg'
            img = cover(Image.open(src).convert('RGB'), (w, h))
            img.save(dest, 'JPEG', quality=90, optimize=True)
            poster(img, wide, f'out/meta/posters/{sid}.webp')
        else:
            dest = f'out/v3/{sid}.mp4'
            r = subprocess.run([
                'ffmpeg', '-v', 'error', '-y', '-i', src, '-t', '12',
                '-map', '0:v:0', '-map_metadata', '-1', '-map_chapters', '-1',
                '-write_tmcd', '0',
                '-vf', f'scale={w}:{h}:force_original_aspect_ratio=increase,'
                       f'crop={w}:{h},fps=30',
                '-an', '-c:v', 'libx264', '-crf', '23', '-preset', 'medium',
                '-maxrate', '2500k', '-bufsize', '5000k',
                '-pix_fmt', 'yuv420p', '-colorspace', 'bt709',
                '-color_primaries', 'bt709', '-color_trc', 'bt709',
                '-movflags', '+faststart', '-f', 'mp4', dest],
                capture_output=True, text=True, timeout=600)
            if r.returncode != 0 or not os.path.exists(dest):
                raise RuntimeError('encode failed: ' + r.stderr[-200:])
            frame = os.path.join('tmp', sid + '.png')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', '1', '-i', dest,
                            '-frames:v', '1', frame], check=True, timeout=120)
            poster(Image.open(frame), wide, f'out/meta/posters/{sid}.webp')
        done[sid] = {'bytes': os.path.getsize(dest)}
        print('ok', sid, done[sid]['bytes'], flush=True)
    except Exception as e:  # noqa: BLE001
        done[sid] = {'error': str(e)[:200]}
        print('FAILED', sid, e, flush=True)
    finally:
        for p in (src,):
            if os.path.exists(p):
                os.remove(p)
json.dump(done, open(f'out/meta/part-{part}.json', 'w'), indent=0)
print(f'part {part}: {sum("bytes" in v for v in done.values())} of {len(mine)} ok')
