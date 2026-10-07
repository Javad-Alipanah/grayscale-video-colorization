"""CPU-only, preview-only source-Y composites of completed Lecture 1 predictions.

Reads original source frame numbers, never seeks by rounded seconds, and uses the
same explicit BT.601 limited-range chroma formula as the approved pilot delivery.
Does not alter render attempts or write acceptance markers.
"""
from pathlib import Path
import argparse, hashlib, json, math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[4]
BASE = Path(__file__).resolve().parent
FF = ROOT / 'work/download-tools/ffmpeg.exe'
RENDER = ROOT / 'work/lecture1-color/render'
MANIFEST = ROOT / 'work/lecture1-color/scenes/manifest.json'
W, H = 960, 720
P = W * H

def balanced(terms):
    if len(terms) == 1:
        return terms[0]
    half = len(terms) // 2
    return '(' + balanced(terms[:half]) + '+' + balanced(terms[half:]) + ')'

def decode(path, frames, fmt, y_only=False):
    expression = balanced([f'eq(n\\,{n})' for n in frames])
    vf = f'trim=end_frame={max(frames)+1},select={expression}'
    if y_only:
        vf += ',extractplanes=y'
    command = [str(FF), '-v', 'error', '-xerror', '-threads', '2',
               '-filter_threads', '2', '-i', str(path), '-an', '-sn',
               '-vf', vf, '-frames:v', str(len(frames)), '-fps_mode',
               'passthrough', '-threads', '2', '-pix_fmt', fmt,
               '-f', 'rawvideo', '-']
    result = subprocess.run(command, capture_output=True, check=True)
    expected = len(frames) * P * (1 if y_only else 3)
    if len(result.stdout) != expected:
        raise ValueError(f'Decode byte count {len(result.stdout)} != {expected}')
    return result.stdout

def convert_yuv(yuv):
    command = [str(FF), '-v', 'error', '-xerror', '-threads', '2',
               '-filter_threads', '2', '-f', 'rawvideo', '-pixel_format',
               'yuv444p', '-video_size', f'{W}x{H}', '-color_range', 'tv',
               '-colorspace', 'bt470bg', '-i', '-', '-threads', '2',
               '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    return subprocess.run(command, input=yuv, capture_output=True, check=True).stdout

def sample(attempt_path, interval, extras):
    attempt = json.loads(attempt_path.read_text())
    if attempt['status'] != 'pending_quality_review' or not attempt.get('full_decode_verified'):
        raise ValueError('Prediction must be fully decoded and pending quality review before sampling')
    if attempt['mode'] != 'colorize':
        raise ValueError('Native preview compositor accepts colorize attempts only')
    manifest = json.loads(MANIFEST.read_text())
    source = Path(manifest['source']['path'])
    prediction = Path(attempt['output'])
    start, count = attempt['start_frame'], attempt['frames']
    folder = BASE / attempt['shot_id'] / f"attempt_{attempt['attempt']:03d}"
    diagnostic_path = folder / 'temporal_diagnostic.json'
    if diagnostic_path.exists():
        diagnostic = json.loads(diagnostic_path.read_text())
        if diagnostic.get('prediction_sha256') == attempt['output_sha256']:
            extras = [*extras, *diagnostic.get('candidate_triplet_local_frames', [])]
    priorities_path = BASE / 'review_priorities.json'
    if priorities_path.exists():
        for priority in json.loads(priorities_path.read_text()).get('dense_ranges', []):
            if priority['shot_id'] == attempt['shot_id']:
                lo, hi = max(0, priority['start_local']), min(count, priority['end_local'])
                if hi > lo:
                    extras = [*extras, *range(lo, hi, priority['sample_step']), hi-1]
    chosen = sorted(set([0, 1, 3, 5, 12, 24, *range(interval, count, interval),
                         count-25, count-13, count-6, count-3, count-2, count-1,
                         *[r['source_frame']-start for r in attempt['references']], *extras]))
    chosen = [n for n in chosen if 0 <= n < count]
    folder.mkdir(parents=True, exist_ok=True)
    rgb = np.frombuffer(decode(prediction, chosen, 'rgb24'), np.uint8).reshape(len(chosen), H, W, 3)
    yy = np.frombuffer(decode(source, [n+start for n in chosen], 'gray', True), np.uint8).reshape(len(chosen), H, W)
    records, images, source_y_digest = [], [], hashlib.sha256()
    for offset in range(0, len(chosen), 8):
        colors = rgb[offset:offset+8].astype(np.float32)
        r, g, b = colors[:,:,:,0], colors[:,:,:,1], colors[:,:,:,2]
        u = np.clip(np.rint(128+(-.168736*r-.331264*g+.5*b)*224/255),16,240).astype(np.uint8)
        v = np.clip(np.rint(128+(.5*r-.418688*g-.081312*b)*224/255),16,240).astype(np.uint8)
        yuv = np.stack([yy[offset:offset+8], u, v], axis=1)
        assert np.array_equal(yuv[:,0], yy[offset:offset+8])
        rendered = np.frombuffer(convert_yuv(yuv.tobytes()), np.uint8).reshape(-1,H,W,3)
        for j, local in enumerate(chosen[offset:offset+8]):
            global_frame = start + local
            path = folder / f'local_{local:06d}_global_{global_frame:06d}.png'
            picture = Image.fromarray(rendered[j])
            picture.save(path)
            images.append(picture.resize((320,240), Image.Resampling.LANCZOS))
            ybytes = yy[offset+j].tobytes()
            source_y_digest.update(ybytes)
            records.append({'local_frame':local, 'global_frame':global_frame,
                            'path':str(path), 'source_y_sha256':hashlib.sha256(ybytes).hexdigest(),
                            'native_sample_y_equal':True,
                            'mean_abs_u_from_neutral':float(np.abs(u[j].astype(float)-128).mean()),
                            'mean_abs_v_from_neutral':float(np.abs(v[j].astype(float)-128).mean())})
    font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 16)
    contacts = []
    for offset in range(0, len(chosen), 12):
        group = chosen[offset:offset+12]
        board = Image.new('RGB', (960, 276*math.ceil(len(group)/3)), '#151515')
        draw = ImageDraw.Draw(board)
        for j, local in enumerate(group):
            x, y = j%3*320, j//3*276
            draw.text((x+4,y+3),f'PREVIEW L{local} G{start+local}',fill='white',font=font)
            board.paste(images[offset+j],(x,y+32))
        target = folder/f'contact_{offset//12:02d}.jpg'
        board.save(target,quality=96)
        contacts.append(str(target))
    result = {'schema_version':1,'status':'preview_only_pending_visual_review',
              'shot_id':attempt['shot_id'],'attempt':attempt['attempt'],
              'prediction_path':str(prediction),'source_path':str(source),
              'source_sha256':manifest['source']['sha256'], 'start_frame':start,'frames':count,
              'samples':records,'contact_sheets':contacts,
              'sample_count':len(chosen),'source_y_sample_sequence_sha256':source_y_digest.hexdigest(),
              'method':'Original native decoded source Y; predicted U/V from explicit BT.601 limited-range formula; yuv444p compositing; FFmpeg tv/bt470bg RGB display conversion. CPU only, two threads.',
              'limitation':'Preview PNGs are RGB display artifacts. Sampled source-Y identity before display conversion is verified; full delivery source-Y verification and continuous motion quality remain outstanding. This is not an acceptance marker.'}
    (folder/'sampling.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'shot_id':attempt['shot_id'],'attempt':attempt['attempt'],'samples':len(chosen),'folder':str(folder)}),flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--shot',required=True)
    parser.add_argument('--attempt',type=int)
    parser.add_argument('--interval',type=int,default=96)
    parser.add_argument('--extra',type=int,nargs='*',default=[])
    args = parser.parse_args()
    paths = sorted((RENDER/args.shot).glob('attempt_*/attempt.json'))
    if args.attempt is not None:
        paths = [p for p in paths if p.parent.name == f'attempt_{args.attempt:03d}']
    if not paths:
        raise FileNotFoundError('No attempt metadata found')
    sample(paths[-1],args.interval,args.extra)
