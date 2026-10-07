"""Independent whole-master Y, audio-EOF and timestamp verification.

For a lossless master of the COMPLETE source only. Batch-local proofs are in the
production engine. No color-quality or full-playback approval is produced here.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def probe(path, ffprobe):
    return json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-show_streams',
        '-of', 'json', str(path)]))['streams']


def decoded_digest(path, ffmpeg, *, audio=False, trim=None, full_yuv=False):
    command = [ffmpeg, '-v', 'error', '-xerror', '-i', str(path)]
    if audio:
        command += ['-map', '0:a:0', '-vn', '-c:a', 'pcm_f32le', '-f', 'f32le', 'pipe:1']
    else:
        filters = []
        if trim is not None:
            filters += [f'trim=start_frame={trim[0]}:end_frame={trim[1]}']
        if not full_yuv:
            filters += ['extractplanes=y']
        command += ['-map', '0:v:0', '-an']
        if filters:
            command += ['-vf', ','.join(filters)]
        if trim is not None:
            command += ['-frames:v', str(trim[1]-trim[0])]
        command += ['-fps_mode', 'passthrough', '-pix_fmt', 'yuv444p' if full_yuv else 'gray', '-f', 'rawvideo', 'pipe:1']
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        h, size = hashlib.sha256(), 0
        try:
            for block in iter(lambda: process.stdout.read(1024*1024), b''):
                h.update(block)
                size += len(block)
        finally:
            process.stdout.close()
            code = process.wait()
        if code:
            errors.seek(0)
            raise RuntimeError(errors.read().decode(errors='replace'))
    return {'sha256': h.hexdigest(), 'bytes': size}


def pts(path, ffprobe):
    data = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-select_streams', 'v:0',
        '-show_frames', '-show_entries', 'frame=best_effort_timestamp:stream=time_base',
        '-of', 'json', str(path)]))
    time_base = Fraction(data['streams'][0]['time_base'])
    return [Fraction(int(f['best_effort_timestamp']))*time_base for f in data['frames']]


def audio_clock(path, ffprobe, sample_rate):
    data = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-select_streams', 'a:0',
        '-show_frames', '-show_entries', 'frame=best_effort_timestamp,nb_samples:stream=time_base',
        '-of', 'json', str(path)]))
    tick = Fraction(data['streams'][0]['time_base'])
    allowed = min(tick, Fraction(1, 1000))
    frames = data['frames']
    if not frames:
        raise ValueError('No decoded audio frames')
    first = Fraction(int(frames[0]['best_effort_timestamp']))*tick
    samples, maximum = 0, Fraction(0)
    for frame in frames:
        count = int(frame['nb_samples'])
        if count <= 0:
            raise ValueError('Invalid decoded audio sample count')
        observed = Fraction(int(frame['best_effort_timestamp']))*tick
        error = abs(observed - first - Fraction(samples, sample_rate))
        maximum = max(maximum, error)
        if error > allowed:
            raise ValueError('Decoded audio clock gap/drift exceeds native rounding (capped at 1 ms)')
        samples += count
    return {'first': first, 'samples': samples, 'tick': tick, 'allowed_error': allowed, 'max_error': maximum}


def verify(source, master, ffmpeg, ffprobe, immutable=None, immutable_start=None, pts_tolerance_ms=0):
    tolerance = Fraction(pts_tolerance_ms)/1000
    if not 0 <= tolerance <= Fraction(1, 1000):
        raise ValueError('Explicit PTS tolerance must be between 0 and 1 ms')
    source, master = Path(source).resolve(), Path(master).resolve()
    if source == master:
        raise ValueError('Source and master must be different files')
    streams = [probe(path, ffprobe) for path in (source, master)]
    videos = []
    audios = []
    for streamset in streams:
        video = [s for s in streamset if s['codec_type'] == 'video']
        audio = [s for s in streamset if s['codec_type'] == 'audio']
        if len(video) != 1 or len(audio) > 1:
            raise ValueError('Expected one video and at most one audio stream; extend policy explicitly')
        if video[0]['pix_fmt'] not in ('yuv420p', 'yuv422p', 'yuv444p', 'gray'):
            raise ValueError('Only native 8-bit planar YUV/gray is supported')
        videos.append(video[0])
        audios.append(audio)
    for key in ('width', 'height', 'r_frame_rate'):
        if videos[0][key] != videos[1][key]:
            raise ValueError(f'Video {key} mismatch')
    if videos[0].get('color_range') != 'tv' or videos[0].get('color_space') not in {'bt470bg', 'smpte170m'}:
        raise ValueError('Source needs an explicit limited-range BT.601 interpretation')
    for key in ('color_range', 'color_space'):
        if videos[0].get(key) != videos[1].get(key):
            raise ValueError(f'Display interpretation changed: {key}')
    y = [decoded_digest(path, ffmpeg) for path in (source, master)]
    area = videos[0]['width']*videos[0]['height']
    if y[0] != y[1] or y[0]['bytes'] == 0 or y[0]['bytes'] % area:
        raise ValueError('Original Y or frame count mismatch')
    timing = [pts(path, ffprobe) for path in (source, master)]
    if len(timing[0]) != len(timing[1]) or len(timing[0]) != y[0]['bytes']//area:
        raise ValueError('Native timestamp/count mismatch')
    maximum_pts_error = max(abs(a-b) for a, b in zip(*timing))
    if maximum_pts_error > tolerance:
        raise ValueError('Native timestamp mismatch exceeds explicitly allowed tolerance')
    if any(b <= a for row in timing for a, b in zip(row, row[1:])):
        raise ValueError('Source PTS is not strictly increasing')
    audio_proof = {'policy': 'no audio stream'}
    if bool(audios[0]) != bool(audios[1]):
        raise ValueError('Audio stream lost or introduced')
    if audios[0]:
        for key in ('sample_rate', 'channels'):
            if audios[0][0].get(key) != audios[1][0].get(key):
                raise ValueError(f'Audio {key} mismatch')
        channels = int(audios[0][0]['channels'])
        inferred = {1: 'mono', 2: 'stereo'}.get(channels)
        layouts = [a[0].get('channel_layout') or inferred for a in audios]
        if layouts[0] != layouts[1] or layouts[0] is None:
            raise ValueError('Audio channel layout is changed or ambiguous')
        audio = [decoded_digest(path, ffmpeg, audio=True) for path in (source, master)]
        if audio[0] != audio[1] or audio[0]['bytes'] == 0:
            raise ValueError('Unfiltered decoded audio through natural EOF differs')
        clocks = [audio_clock(path, ffprobe, int(audios[0][0]['sample_rate'])) for path in (source, master)]
        if clocks[0]['first'] != clocks[1]['first'] or clocks[0]['samples'] != clocks[1]['samples']:
            raise ValueError('Effective decoded audio start/sample clock mismatch')
        if clocks[0]['samples']*int(audios[0][0]['channels'])*4 != audio[0]['bytes']:
            raise ValueError('Decoded audio-frame sample count disagrees with PCM payload')
        audio_proof = dict(audio[0], policy='all decoded pcm_f32le through EOF; codec priming honored; no duration trim',
                          decoded_clocks=[{key: str(value) if isinstance(value, Fraction) else value
                                           for key, value in clock.items()} for clock in clocks])
    reuse = None
    if immutable is not None:
        if immutable_start is None or immutable_start < 0:
            raise ValueError('Immutable reuse requires a nonnegative global start frame')
        reference = Path(immutable).resolve()
        stream = next(s for s in probe(reference, ffprobe) if s['codec_type'] == 'video')
        if (stream['width'], stream['height'], stream['pix_fmt']) != (videos[0]['width'], videos[0]['height'], 'yuv444p'):
            raise ValueError('Immutable comparison requires native same-size yuv444p reference')
        expected = decoded_digest(reference, ffmpeg, full_yuv=True)
        if expected['bytes'] == 0 or expected['bytes'] % (3*area):
            raise ValueError('Invalid immutable reference')
        end = immutable_start + expected['bytes']//(3*area)
        actual = decoded_digest(master, ffmpeg, trim=(immutable_start, end), full_yuv=True)
        if expected != actual:
            raise ValueError('Immutable native YUV range differs')
        reuse = {'reference_sha256': sha(reference), 'start_frame': immutable_start,
                 'end_frame': end, 'decoded': expected}
    return {'status': 'whole_master_technical_preservation_pass',
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'source_sha256': sha(source), 'master_sha256': sha(master),
            'frame_count': len(timing[0]), 'original_y': y[0], 'original_audio': audio_proof,
            'color_range': videos[1]['color_range'], 'color_space': videos[1]['color_space'],
            'every_video_pts_equal': maximum_pts_error == 0,
            'every_video_pts_within_declared_tolerance': True,
            'max_video_pts_error_seconds': str(maximum_pts_error),
            'allowed_video_pts_error_seconds': str(tolerance), 'immutable_reuse': reuse,
            'visual_acceptance': False, 'continuous_playback_review': 'not_performed_by_this_tool'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--master', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--ffmpeg', default=os.environ.get('COLOR_FFMPEG', 'ffmpeg'))
    parser.add_argument('--ffprobe', default=os.environ.get('COLOR_FFPROBE', 'ffprobe'))
    parser.add_argument('--immutable', type=Path)
    parser.add_argument('--immutable-start', type=int)
    parser.add_argument('--pts-tolerance-ms', type=Fraction, default=Fraction(0),
                        help='Default exact. Explicit 0..1 ms allowance for reviewed container rounding.')
    args = parser.parse_args()
    if args.report.resolve() in {args.source.resolve(), args.master.resolve(), (args.immutable or args.source).resolve()}:
        raise ValueError('Report cannot overwrite media')
    result = verify(args.source, args.master, args.ffmpeg, args.ffprobe, args.immutable, args.immutable_start,
                    args.pts_tolerance_ms)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
