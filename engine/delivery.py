"""CPU-only incremental source-Y masters and draft batch/final assembly.

All artifacts stay under render/delivery until independent visual review and
explicit promotion. FFV1/PCM master equalities do not apply to the lossy preview.
"""
from __future__ import annotations
import argparse
import contextlib
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import time
import numpy as np
import production as p
import scientific_mask as sm

BASE = p.RENDER / 'delivery'
MERGE_METHOD = 'native-Y + limited-range BT.601 prediction UV; float32 formula v1'


def merge_frame(y_bytes, rgb):
    if len(y_bytes) != rgb.shape[0] * rgb.shape[1] or rgb.shape[-1] != 3:
        raise ValueError('Native Y and RGB prediction geometry differ')
    values = rgb.astype(np.float32)
    red, green, blue = values[:, :, 0], values[:, :, 1], values[:, :, 2]
    u = np.clip(np.rint(128 + (-.168736 * red - .331264 * green + .5 * blue) * 224 / 255), 16, 240).astype(np.uint8)
    v = np.clip(np.rint(128 + (.5 * red - .418688 * green - .081312 * blue) * 224 / 255), 16, 240).astype(np.uint8)
    return y_bytes + u.tobytes() + v.tobytes()


def audio_sample_interval(start, end, sample_rate, fps_num, fps_den):
    values = [Fraction(frame * fps_den * sample_rate, fps_num) for frame in [start, end]]
    if any(value.denominator != 1 for value in values):
        raise ValueError('Frame boundaries do not fall on exact native audio samples; explicit alignment policy required')
    return tuple(int(value) for value in values)


def validate_merged_coverage(shots, merges):
    if not shots:
        raise ValueError('Empty delivery selection')
    expected = shots[0]['start_frame']
    for shot in shots:
        merge = merges.get(shot['id'])
        if not merge or merge.get('status') != 'draft_verified' or not merge.get('exact_source_y') or not merge.get('full_decode_verified'):
            raise ValueError(f'Shot has no verified source-Y merge: {shot["id"]}')
        if (shot['start_frame'], merge['start_frame'], merge['end_frame'], merge['frames']) != (
                expected, expected, shot['end_frame'], shot['end_frame']-expected):
            raise ValueError(f'Merged coverage gap, overlap or mismatched shot: {shot["id"]}')
        expected = shot['end_frame']
    return shots[0]['start_frame'], expected


def override_base_context(document, merges, registry, identity, runtime, callback):
    """Resolve a cross-batch outgoing baseline without including it in assembly."""
    context = dict(merges)
    shots = {shot['id']: shot for shot in document['shots']}
    for shot_id, base in merges.items():
        override = registry.get(shot_id)
        if not override:
            continue
        saved = p.read_json(override['receipt'])
        outgoing_id = saved.get('outgoing_shot_id')
        if not outgoing_id or outgoing_id in context:
            continue
        outgoing = shots.get(outgoing_id)
        if not outgoing or outgoing['end_frame'] != base['start_frame']:
            raise ValueError('Cross-batch chroma context is not the adjacent original shot')
        attempt = choose_attempt(outgoing, identity, runtime)
        if attempt is None:
            raise ValueError('Cross-batch outgoing context lacks verified inference')
        context[outgoing_id] = reviewed_reclaimed_base(outgoing,attempt,identity) or merge_one(document, outgoing, attempt, identity, callback)
    return context


def reviewed_reclaimed_base(shot,attempt,identity):
    """Use historical base provenance only to select its preserved reviewed repair.

    This does not claim missing media exists and must never feed a pixel decoder.
    It avoids remuxing identical pixels into a new container hash after cleanup.
    """
    if shot.get('scientific_screen_scene_id'):return None
    directory=BASE/'shots'/shot['id']/f'attempt_{attempt["attempt"]:03d}_{attempt["output_sha256"][:12]}'
    marker=directory/'merge.json'
    if not marker.is_file():return None
    saved=p.read_json(marker)
    if Path(saved['output']).is_file():return None
    expected=p.json_digest(dict(prediction=attempt['output_sha256'],source=identity['sha256'],start=shot['start_frame'],end=shot['end_frame'],method=MERGE_METHOD,mode=shot['mode']))
    if saved.get('fingerprint')!=expected or saved.get('status')!='draft_verified' or not saved.get('exact_source_y') or not saved.get('full_decode_verified'):return None
    registry_path=p.HERE/'source_y_overrides.json'
    if not registry_path.is_file():return None
    override=p.read_json(registry_path).get(shot['id'])
    if not override or override.get('status') not in {'active_pending_quality_review','accepted'}:return None
    treatment=p.read_json(override['receipt'])
    if treatment.get('base_output_sha256')!=saved['output_sha256'] or treatment.get('output_sha256')!=override['output_sha256']:return None
    proof=None
    for path in p.HERE.glob('cleanup_*/deletion_receipt.json'):
        receipt=p.read_json(path)
        if receipt.get('status')!='complete':continue
        for row in receipt.get('files',[]):
            replacement=row.get('replacement_proof',{})
            if (row.get('status')=='deleted' and row.get('path')==saved['output'] and row.get('sha256')==saved['output_sha256']
                and replacement.get('merge_receipt_sha256')==p.sha256(marker) and replacement.get('selected_repair_output_sha256')==override['output_sha256']):
                proof=dict(path=str(path),sha256=p.sha256(path),replacement=replacement);break
        if proof:break
    if proof is None:return None
    replacement=proof['replacement']
    for key,hashkey in [('local_review','local_review_sha256'),('replacement_integrity','replacement_integrity_sha256'),('assembled_review','assembled_review_sha256')]:
        if p.sha256(replacement[key])!=replacement[hashkey]:raise ValueError('Reclaimed base review provenance changed')
    if p.sha256(attempt['output'])!=attempt['output_sha256']:raise ValueError('Retained prediction for reclaimed base changed')
    if p.sha256(treatment['output'])!=override['output_sha256']:raise ValueError('Selected reviewed repair for reclaimed base changed')
    if not all(treatment.get(k) is True for k in ['exact_source_y','full_decode_verified','exact_outside_support_uv']):raise ValueError('Selected repair lacks complete preservation proof')
    p.reject_failed_chroma_review(shot['id'],override['output_sha256'])
    return dict(saved,historical_base_media_reclaimed=True,cleanup_provenance=proof,
        usage_restriction='Historical source-Y base identity only; use current preserved chroma repair for pixels. Rebuild explicitly if an uncorrected pixel baseline is needed.')


def apply_source_y_override(base, registry, all_bases=None):
    """Bind an optional chroma-only draft to the exact current source-Y master."""
    override = registry.get(base['shot_id'])
    if not override:
        if base.get('historical_base_media_reclaimed'):raise ValueError('A reclaimed base requires its preserved reviewed override')
        return base
    if override.get('status', 'active_pending_quality_review') not in {'active_pending_quality_review', 'accepted'}:
        raise p.QualityReviewRejected('Chroma override is held for changes; delivery cannot select it')
    saved = p.read_json(override['receipt'])
    if saved.get('base_output_sha256') != base['output_sha256']:
        raise ValueError('Chroma override base changed; treatment must be revalidated')
    if saved.get('outgoing_output_sha256'):
        outgoing_id = saved.get('outgoing_shot_id') or next((key for key, value in (all_bases or {}).items()
            if value['end_frame'] == saved['start_frame']), None)
        outgoing = (all_bases or {}).get(outgoing_id)
        # Some compound candidates were reviewed against the selected preceding
        # treatment. Resolve that exact hash only, including its own base/media
        # checks. Strictly decreasing adjacent ranges prevent dependency cycles.
        if outgoing and outgoing['output_sha256'] != saved['outgoing_output_sha256']:
            prior_choice = registry.get(outgoing_id, {})
            if (prior_choice.get('output_sha256') == saved['outgoing_output_sha256']
                    and outgoing['end_frame'] == base['start_frame']
                    and outgoing['start_frame'] < base['start_frame']):
                outgoing = apply_source_y_override(outgoing, registry, all_bases)
        if not outgoing or outgoing['output_sha256'] != saved['outgoing_output_sha256']:
            raise ValueError('Chroma override outgoing base changed; treatment must be revalidated')
    if not all(saved.get(flag) is True for flag in ['exact_source_y', 'full_decode_verified', 'exact_outside_support_uv']):
        raise ValueError('Chroma override lacks source-Y/outside-support proof')
    if saved.get('status') != 'draft_verified' or saved['output_sha256'] != override['output_sha256']:
        raise ValueError('Chroma override is not a verified draft')
    if any(saved[field] != base[field] for field in ['shot_id', 'start_frame', 'end_frame', 'frames']):
        raise ValueError('Chroma override changes shot coverage')
    if p.sha256(saved['output']) != saved['output_sha256']:
        raise ValueError('Chroma override payload changed')
    p.reject_failed_chroma_review(saved['shot_id'], saved['output_sha256'])
    selected = dict(base, output=saved['output'], output_sha256=saved['output_sha256'],historical_base_media_reclaimed=False,
        base_output=base['output'], base_output_sha256=base['output_sha256'],
        chroma_treatment_receipt=override['receipt'], chroma_treatment=saved['method'],
        quality_acceptance='pending')
    if base.get('scientific_mask_receipt'):
        # These exact equalities describe the uncomposited scene hypothesis.
        # Later source-alpha mixtures/material treatments have their own
        # bounded proofs and must not inherit them as whole-output claims.
        selected['base_scientific_mask_guarantees'] = {
            key: base.get(key) for key in ['exact_source_uv_inside_mask', 'exact_prediction_uv_outside_mask']}
        selected['scientific_mask_proof_scope'] = 'Base scene hypothesis before the selected chroma treatment; consult its bound receipt and scientific-scope review for final pixels.'
        selected['exact_source_uv_inside_mask'] = None
        selected['exact_prediction_uv_outside_mask'] = None
    return selected


def audio_probe(source):
    command = [str(p.FFPROBE), '-v', 'error', '-select_streams', 'a:0', '-show_streams', '-of', 'json', str(source)]
    stream = json.loads(subprocess.check_output(command))['streams'][0]
    start = Fraction(stream.get('start_time', '0'))
    if start != 0:
        if start > 0 or stream.get('codec_name') != 'aac':
            raise ValueError('Nonzero source audio start requires explicit alignment; refusing to move samples silently')
        from audio_clock import probe_clock
        stream['decoded_clock_proof'] = probe_clock(source, stream, p.FFPROBE)
    return stream


def read_exact(stream, size):
    chunks, total = [], 0
    while total < size:
        part = stream.read(size-total)
        if not part:
            break
        chunks.append(part)
        total += len(part)
    return b''.join(chunks)


def decoder(path, fmt, log, start=0, frames=None, extract_y=False):
    filters = []
    if frames is not None:
        filters.append(f'trim=start_frame={start}:end_frame={start+frames},setpts=PTS-STARTPTS')
    if extract_y:
        filters.append('extractplanes=y')
    command = [str(p.FFMPEG), '-v', 'error', '-xerror', '-threads', '2', '-filter_threads', '2', '-i', str(path), '-map', '0:v:0']
    if filters:
        command += ['-vf', ','.join(filters)]
    if frames is not None:
        command += ['-frames:v', str(frames)]
    command += ['-an', '-sn', '-fps_mode', 'passthrough', '-threads', '2', '-f', 'rawvideo', '-pix_fmt', fmt, 'pipe:1']
    return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log)


def hash_command(command, logfile, callback=None):
    digest, size, last = hashlib.sha256(), 0, time.monotonic()
    with Path(logfile).open('w') as log:
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log)
        try:
            for block in iter(lambda: child.stdout.read(4*1024*1024), b''):
                digest.update(block)
                size += len(block)
                if callback and time.monotonic()-last >= 5:
                    callback(decoded_bytes=size)
                    last = time.monotonic()
        finally:
            child.stdout.close()
        if child.wait():
            raise RuntimeError(f'Decode/hash failed; inspect {logfile}')
    return {'sha256': digest.hexdigest(), 'decoded_bytes': size}


def video_y_hash(path, logfile, start=0, frames=None, callback=None):
    command = [str(p.FFMPEG), '-v', 'error', '-xerror', '-threads', '2', '-filter_threads', '2', '-i', str(path), '-map', '0:v:0']
    filters = []
    if frames is not None:
        filters.append(f'trim=start_frame={start}:end_frame={start+frames}')
    filters.append('extractplanes=y')
    command += ['-vf', ','.join(filters), '-an', '-sn', '-fps_mode', 'passthrough', '-threads', '2',
        *(['-frames:v', str(frames)] if frames is not None else []), '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1']
    return hash_command(command, logfile, callback)


def audio_trim_filter(samples):
    return f'atrim=start_sample={samples[0]}' + (f':end_sample={samples[1]}' if samples[1] is not None else '')


def audio_hash(path, logfile, samples=None, callback=None):
    command = [str(p.FFMPEG), '-v', 'error', '-xerror', '-threads', '2', '-i', str(path), '-map', '0:a:0', '-vn', '-sn']
    if samples is not None:
        command += ['-af', audio_trim_filter(samples)]
    command += ['-c:a', 'pcm_f32le', '-f', 'f32le', 'pipe:1']
    return hash_command(command, logfile, callback)


def run_logged(command, logfile, callback=None):
    with Path(logfile).open('w') as log:
        child = subprocess.Popen(command, stdout=log, stderr=log)
        while child.poll() is None:
            if callback:
                callback(process_pid=child.pid)
            time.sleep(5)
    if child.returncode:
        raise RuntimeError(f'Media command failed ({child.returncode}); inspect {logfile}')


def verify_timestamps(path, frames, source):
    command = [str(p.FFPROBE), '-v', 'error', '-select_streams', 'v:0', '-show_packets',
        '-show_entries', 'packet=pts_time', '-of', 'json', str(path)]
    times = sorted(float(packet['pts_time']) for packet in json.loads(subprocess.check_output(command))['packets'])
    if len(times) != frames or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Output video packet timestamps have missing, repeated or reversed frames')
    error = max(abs(value-i*source['fps_den']/source['fps_num']) for i, value in enumerate(times))
    if error > .000501:
        raise ValueError(f'Output cadence differs from exact source rate by {error}s')
    return {'presentation_timestamps': frames, 'strictly_increasing': True, 'max_cadence_error_seconds': error,
        'first_pts_seconds': times[0], 'last_pts_seconds': times[-1]}


def verify_video_geometry(path, source, codec='ffv1'):
    stream = p.probe(path)
    if (stream['width'], stream['height'], Fraction(stream['r_frame_rate']), stream['codec_name']) != (
            source['width'], source['height'], Fraction(source['fps_num'], source['fps_den']), codec):
        raise ValueError('Delivery video geometry, rate or codec differs from source requirements')
    if codec == 'ffv1' and stream['pix_fmt'] != 'yuv444p':
        raise ValueError('Lossless source-Y master must be native yuv444p')
    return stream


def choose_attempt(shot, identity, runtime):
    overrides_path = p.HERE/'prediction_overrides.json'
    overrides = p.read_json(overrides_path) if overrides_path.exists() else {}
    override = overrides.get(shot['id'])
    if override and override.get('status') in {'active_pending_quality_review', 'accepted'}:
        record = p.read_json(override['attempt_path'])
        parent = p.read_json(record['parent_attempt_path'])
        parent_doc = p.validate_manifest(p.read_json(record['parent_manifest_path']))
        parent_shot = next(item for item in parent_doc['shots'] if item['id'] == parent['shot_id'])
        parent_approval = p.approved_references(parent_shot)
        if parent_approval is None or parent.get('fingerprint') != p.fingerprint(parent_shot, identity, runtime, parent_approval):
            return None
        if parent['status'] not in {'pending_quality_review', 'accepted'} or record['status'] not in {'pending_quality_review', 'accepted'}:
            return None
        if not record.get('exact_parent_rgb_crop') or not record.get('full_decode_verified') or record.get('output_sha256') != override['output_sha256']:
            raise ValueError('Correction override is not a verified immutable RGB crop')
        if record.get('parent_output_sha256') != parent.get('output_sha256') or record.get('parent_output_sha256') != override.get('parent_output_sha256'):
            raise ValueError('Correction parent hash changed')
        if (record['start_frame'], record['end_frame'], record['frames']) != (shot['start_frame'], shot['end_frame'], shot['frames']):
            raise ValueError('Correction override changes original coverage')
        return record
    correction_plan = p.HERE/'corrections/plan.json'
    if correction_plan.exists():
        targets = {target for group in p.read_json(correction_plan)['groups'] for target in group['targets']}
        if shot['id'] in targets:
            return None
    approval = p.approved_references(shot)
    if approval is None:
        return None
    fingerprint = p.fingerprint(shot, identity, runtime, approval)
    records = [a for a in p.all_attempts() if a['shot_id'] == shot['id'] and a.get('fingerprint') == fingerprint
        and a['status'] in {'pending_quality_review', 'accepted'} and a.get('full_decode_verified')
        and a.get('verified_decoded_frames') == shot['frames']]
    return max(records, key=lambda a: a['attempt'], default=None)


def merge_one(document, shot, attempt, identity, callback):
    # Scientific masks belong to a camera/scene hypothesis. Applying them here
    # also handles outgoing overlap renders BEFORE later dissolve compositing.
    config = sm.load(shot, document['source'], identity)
    base = _merge_one_base(document, shot, attempt, identity, callback)
    return sm.apply(document, shot, attempt, base, identity, config, callback)


def _merge_one_base(document, shot, attempt, identity, callback):
    token = f'attempt_{attempt["attempt"]:03d}_{attempt["output_sha256"][:12]}'
    directory = BASE / 'shots' / shot['id'] / token
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / 'merge.json'
    fingerprint = p.json_digest({'prediction': attempt['output_sha256'], 'source': identity['sha256'],
        'start': shot['start_frame'], 'end': shot['end_frame'], 'method': MERGE_METHOD, 'mode': shot['mode']})
    if marker.exists():
        saved = p.read_json(marker)
        if saved.get('status') == 'draft_verified' and saved.get('fingerprint') == fingerprint:
            if Path(saved['output']).is_file() and p.sha256(saved['output']) == saved.get('output_sha256'):
                return saved
    if p.sha256(attempt['output']) != attempt['output_sha256']:
        raise ValueError('Prediction output changed after render verification')
    source = document['source']
    width, height, frames = source['width'], source['height'], shot['frames']
    pixels = width*height
    rate = f'{source["fps_num"]}/{source["fps_den"]}'
    output = directory / 'source_y_master.mkv'
    record = {'schema_version': 1, 'shot_id': shot['id'], 'model_attempt': attempt['attempt'],
        'status': 'merging', 'quality_acceptance': 'pending', 'started_at': p.utc(),
        'start_frame': shot['start_frame'], 'end_frame': shot['end_frame'], 'frames': frames,
        'fingerprint': fingerprint, 'prediction_path': attempt['output'], 'prediction_sha256': attempt['output_sha256'],
        'source_sha256': identity['sha256'], 'mode': shot['mode'], 'output': str(output),
        'method': MERGE_METHOD, 'audio': 'Video-only shot. Batch/final master receives original decoded PCM separately.'}
    p.atomic_json(marker, record)
    started = time.perf_counter()
    try:
        if shot['mode'] == 'reusable_approved_master':
            output = Path(attempt['output'])
            record['output'] = str(output)
            source_y = {'sha256': attempt['reuse_proof']['source_y_sha256'], 'decoded_bytes': frames*pixels}
            record['method'] = 'Existing approved source-Y master referenced without copying; joins still pending review.'
        elif shot['mode'] == 'passthrough':
            command = [str(p.FFMPEG), '-v', 'error', '-xerror', '-y', '-threads', '2', '-filter_threads', '2',
                '-i', attempt['output'], '-map', '0:v:0', '-an', '-sn', '-vf', 'format=yuv444p', '-fps_mode', 'passthrough',
                '-c:v', 'ffv1', '-level', '3', '-threads', '2', '-pix_fmt', 'yuv444p', '-color_range', 'tv', '-colorspace', source.get('color_space','bt470bg'), str(output)]
            run_logged(command, directory/'merge.log', callback)
            source_y = video_y_hash(attempt['output'], directory/'source_y.log', callback=callback)
            record['method'] = 'Source passthrough, original Y with native-source chroma upsampled to delivery yuv444p.'
        else:
            source_clip = attempt['source_clip']
            source_y_digest = hashlib.sha256()
            command = [str(p.FFMPEG), '-v', 'error', '-xerror', '-y', '-f', 'rawvideo', '-pix_fmt', 'yuv444p',
                '-s', f'{width}x{height}', '-framerate', rate, '-i', 'pipe:0', '-an', '-sn',
                '-c:v', 'ffv1', '-level', '3', '-threads', '2', '-pix_fmt', 'yuv444p', '-color_range', 'tv', '-colorspace', source.get('color_space','bt470bg'), str(output)]
            with (directory/'source_decode.log').open('w') as slog, (directory/'prediction_decode.log').open('w') as plog, (directory/'merge_encode.log').open('w') as elog:
                original = decoder(source_clip['path'], 'gray', slog, attempt['input_start_frame'], frames, True)
                prediction = decoder(attempt['output'], 'rgb24', plog)
                encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=elog, stderr=elog)
                try:
                    for index in range(frames):
                        y = read_exact(original.stdout, pixels)
                        rgb = read_exact(prediction.stdout, pixels*3)
                        if len(y) != pixels or len(rgb) != pixels*3:
                            raise ValueError(f'Short source/prediction decode at local frame {index}')
                        source_y_digest.update(y)
                        image = np.frombuffer(rgb, np.uint8).reshape(height, width, 3)
                        encoder.stdin.write(merge_frame(y, image))
                        if index % 48 == 0 or index+1 == frames:
                            callback(done=index+1, total=frames)
                    if original.stdout.read(1) or prediction.stdout.read(1):
                        raise ValueError('Source/prediction contains excess frames')
                finally:
                    original.stdout.close()
                    prediction.stdout.close()
                    with contextlib.suppress(BrokenPipeError, OSError):
                        encoder.stdin.close()
                    codes = [child.wait() for child in [original, prediction, encoder]]
                if any(codes):
                    raise RuntimeError(f'Source-Y merge decode/encode failed: {codes}')
            source_y = {'sha256': source_y_digest.hexdigest(), 'decoded_bytes': frames*pixels}
            record['source_clip_mapping'] = source_clip
        callback(phase='verifying_source_y')
        verify_video_geometry(output, source)
        merged_y = video_y_hash(output, directory/'merged_y_verify.log', callback=callback)
        if merged_y != source_y or merged_y['decoded_bytes'] != frames*pixels:
            raise ValueError('Merged output changed source Y or frame count')
        timing = verify_timestamps(output, frames, source)
        record.update(status='draft_verified', exact_source_y=True, full_decode_verified=True,
            verified_decoded_frames=frames, source_y=source_y, merged_y=merged_y, timing=timing,
            output_sha256=p.sha256(output), finished_at=p.utc(), wall_seconds=time.perf_counter()-started)
    except BaseException as error:
        record.update(status='failed', error=str(error), finished_at=p.utc(), wall_seconds=time.perf_counter()-started)
        raise
    finally:
        p.atomic_json(marker, record)
    print(json.dumps({'stage': 'shot_source_y_ready', 'shot_id': shot['id'], 'output': str(output),
        'frames': frames, 'exact_source_y': True}), flush=True)
    return record


def prepare_audio(document, start, end, identity, directory, callback):
    source = document['source']
    stream = audio_probe(identity['path'])
    rate, channels = int(stream['sample_rate']), stream['channels']
    samples = audio_sample_interval(start, end, rate, source['fps_num'], source['fps_den'])
    full_source = start == 0 and end == source['frame_count']
    source_end = end == source['frame_count']
    # The final picture boundary need not equal AAC's decoded sample endpoint.
    # Keep every remaining original sample through natural EOF, just as the
    # full-lecture path does; interior boundaries still require exact samples.
    applied_samples = None if full_source else (samples[0], None if source_end else samples[1])
    audio = directory/'source_pcm_f32le.mka'
    marker = directory/'audio_verification.json'
    if marker.exists():
        previous = p.read_json(marker)
        requested_interval = list(applied_samples) if applied_samples is not None else None
        if (previous.get('status') == 'verified' and previous['source_sha256'] == identity['sha256']
                and previous.get('selected_sample_interval') == requested_interval
                and audio.is_file() and p.sha256(audio) == previous['output_sha256']):
            return previous
    command = [str(p.FFMPEG), '-v', 'error', '-xerror', '-y', '-threads', '2', '-i', identity['path'], '-map', '0:a:0', '-vn', '-sn']
    if applied_samples is not None:
        command += ['-af', audio_trim_filter(applied_samples)+',asetpts=N/SR/TB']
    command += ['-c:a', 'pcm_f32le', str(audio)]
    run_logged(command, directory/'audio_extract.log', callback)
    original_hash = audio_hash(identity['path'], directory/'source_audio_hash.log', applied_samples, callback)
    output_hash = audio_hash(audio, directory/'pcm_audio_hash.log', callback=callback)
    if original_hash != output_hash:
        raise ValueError('Aligned PCM differs from original decoded source audio')
    actual_samples = output_hash['decoded_bytes']//(4*channels)
    if not source_end and actual_samples != samples[1]-samples[0]:
        raise ValueError('Source audio ended before the requested exact sample boundary')
    result = {'status': 'verified', 'path': str(audio), 'source_sha256': identity['sha256'],
        'start_frame': start, 'end_frame': end, 'sample_rate': rate, 'channels': channels,
        'selected_sample_interval': applied_samples, 'samples_per_channel': actual_samples,
        'nominal_video_sample_interval': samples, 'natural_source_audio_eof_retained': source_end,
        'exact_unfiltered_decoded_source_pcm': True, 'source_audio': original_hash, 'output_audio': output_hash,
        'output_sha256': p.sha256(audio), 'command': command,
        'policy': 'Original decoded float32 samples, no resampling or audio enhancement; exact interior frame-boundary trims, all remaining source samples through natural EOF for the final range.'}
    p.atomic_json(marker, result)
    return result


def full_decode_preview(path, logfile, callback):
    command = [str(p.FFMPEG), '-v', 'error', '-xerror', '-threads', '2', '-i', str(path), '-map', '0:v:0', '-map', '0:a:0',
        '-fps_mode', 'passthrough', '-progress', 'pipe:1', '-nostats', '-f', 'null', '-']
    with Path(logfile).open('w') as log:
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log, text=True)
        frames, ended = 0, False
        for line in child.stdout:
            if line.startswith('frame='):
                frames = int(line.split('=', 1)[1])
                callback(decoded_frames=frames)
            if line.strip() == 'progress=end':
                ended = True
        child.stdout.close()
        if child.wait() or not ended:
            raise ValueError('Preview full decoding failed')
    return frames


def assemble_scope(document, shots, merges, identity, scope, callback):
    start, end = validate_merged_coverage(shots, merges)
    source = document['source']
    frames = end-start
    key = p.json_digest({'source': identity['sha256'], 'shots': [(shot['id'], merges[shot['id']]['output_sha256']) for shot in shots],
        'start': start, 'end': end, 'audio_policy': 'source float32 PCM', 'delivery_version': 1})
    directory = BASE/'batches'/scope/f'assembly_{key[:16]}'
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory/'assembly.json'
    master, preview = directory/'draft_master_ffv1_pcm.mkv', directory/'draft_preview_h264.mp4'
    if marker.exists():
        saved = p.read_json(marker)
        if saved.get('status') == 'draft_verified_pending_visual_review' and saved.get('fingerprint') == key:
            if master.is_file() and preview.is_file() and p.sha256(master) == saved.get('master_sha256') and p.sha256(preview) == saved.get('preview_sha256'):
                return saved
    result = {'schema_version': 1, 'status': 'assembling', 'quality_acceptance': 'pending', 'scope': scope,
        'start_frame': start, 'end_frame': end, 'frames': frames, 'duration_seconds': frames*source['fps_den']/source['fps_num'],
        'fingerprint': key, 'source_sha256': identity['sha256'], 'started_at': p.utc(),
        'master': str(master), 'preview': str(preview), 'shots': [merges[shot['id']] for shot in shots]}
    p.atomic_json(marker, result)
    started = time.perf_counter()
    try:
        callback(phase='preparing_original_pcm')
        audio = prepare_audio(document, start, end, identity, directory, callback)
        listing = directory/'video_concat.txt'
        paths = [Path(merges[shot['id']]['output']) for shot in shots]
        listing.write_text(''.join("file '" + str(path).replace('\\', '/').replace("'", "'\\''") + "'\n" for path in paths), encoding='utf-8')
        callback(phase='assembling_lossless_master')
        # Rebuild presentation timestamps from the global output frame number.
        # This prevents rounded Matroska segment durations accumulating at joins.
        command = [str(p.FFMPEG), '-v', 'error', '-xerror', '-y', '-threads', '2', '-filter_threads', '2',
            '-f', 'concat', '-safe', '0', '-i', str(listing), '-i', audio['path'], '-map', '0:v:0', '-map', '1:a:0',
            '-vf', f'settb=1/{source["fps_num"]},setpts=N*{source["fps_den"]}', '-fps_mode', 'passthrough',
            '-c:v', 'ffv1', '-level', '3', '-threads', '2', '-pix_fmt', 'yuv444p',
            '-color_range', 'tv', '-colorspace', source.get('color_space','bt470bg'), '-c:a', 'copy', str(master)]
        run_logged(command, directory/'assemble.log', callback)
        callback(phase='verifying_master_native_y_and_pcm')
        verify_video_geometry(master, source)
        original_y = video_y_hash(identity['path'], directory/'original_y_hash.log', start, frames, callback)
        master_y = video_y_hash(master, directory/'master_y_hash.log', callback=callback)
        if original_y != master_y or master_y['decoded_bytes'] != frames*source['width']*source['height']:
            raise ValueError('Assembled master Y differs from full original source interval')
        master_audio = audio_hash(master, directory/'master_audio_hash.log', callback=callback)
        if master_audio != audio['source_audio']:
            raise ValueError('Assembled master PCM differs from original decoded source audio')
        master_audio_stream = audio_probe(master)
        if (master_audio_stream['codec_name'], int(master_audio_stream['sample_rate']), master_audio_stream['channels']) != ('pcm_f32le', audio['sample_rate'], audio['channels']):
            raise ValueError('Master audio codec, sample rate or channels changed')
        master_timing = verify_timestamps(master, frames, source)
        callback(phase='encoding_h264_preview')
        command = [str(p.FFMPEG), '-v', 'error', '-xerror', '-y', '-threads', '2', '-filter_threads', '2', '-i', str(master),
            '-map', '0:v:0', '-map', '0:a:0', '-vf', f'settb=1/{source["fps_num"]},setpts=N*{source["fps_den"]}',
            '-fps_mode', 'passthrough', '-c:v', 'libx264', '-preset', 'medium', '-crf', '16', '-threads', '2', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k', '-video_track_timescale', str(source['fps_num']), '-movflags', '+faststart', str(preview)]
        run_logged(command, directory/'preview_encode.log', callback)
        callback(phase='verifying_preview')
        verify_video_geometry(preview, source, 'h264')
        if full_decode_preview(preview, directory/'preview_decode_verify.log', callback) != frames:
            raise ValueError('Preview decoded frame count differs from source interval')
        preview_timing = verify_timestamps(preview, frames, source)
        result.update(status='draft_verified_pending_visual_review', exact_source_y=True, exact_source_pcm=True,
            full_decode_verified=True, original_y=original_y, master_y=master_y, source_audio=audio, master_audio=master_audio,
            master_timing=master_timing, preview_timing=preview_timing,
            master_audio_codec=master_audio_stream['codec_name'],
            master_sha256=p.sha256(master), preview_sha256=p.sha256(preview), finished_at=p.utc(), wall_seconds=time.perf_counter()-started,
            limitations=['Source Y and PCM equality apply to the FFV1/PCM master, not the lossy H264/AAC preview.',
                'Colors remain interpretive. Stream checks do not resolve chroma seams, leakage, or unsampled temporal defects.',
                'These are working drafts and require independent visual review before promotion to outputs.'])
    except BaseException as error:
        result.update(status='failed', error=str(error), finished_at=p.utc())
        raise
    finally:
        p.atomic_json(marker, result)
    return result


def scientific_scope_hold(scope, shots, merges, identity):
    """Masks protect hypotheses; mixed scientific scenes need independent QA too."""
    if not any(shot.get('scientific_screen_scene_id') for shot in shots):
        return None
    marker = p.PROJECT/'scenes/qc/projection_masks'/f'{scope}_delivery_ready.json'
    required = {shot['id']: merges[shot['id']]['output_sha256'] for shot in shots}
    if not marker.exists():
        return dict(reason='Scientific masks and their source-dissolve composites require independent native review before batch assembly.',
            ready_marker=str(marker),selected_output_sha256=required)
    review = p.read_json(marker)
    if (review.get('status') != 'scientific_scope_review_pass' or review.get('source_sha256') != identity['sha256']
            or review.get('selected_output_sha256') != required or review.get('scene_hypothesis_masks_reviewed') is not True
            or review.get('source_dissolve_composites_reviewed') is not True):
        return dict(reason='Scientific-scope review is missing, incomplete, or bound to earlier selected outputs.',
            ready_marker=str(marker),selected_output_sha256=required)
    return None


def watch(args):
    document = p.validate_manifest(p.read_json(args.manifest))
    shots = [shot for shot in document['shots'] if not args.batch or shot['batch_id'] == args.batch]
    if not shots or (not args.batch and document.get('pending_ranges')):
        raise ValueError('Scope is empty or full lecture planning still has pending intervals')
    scope = args.batch or getattr(args, 'scope', 'full')
    if not __import__('re').fullmatch(r'[A-Za-z0-9_-]+',scope):
        raise ValueError('Invalid delivery scope identifier')
    status_path = getattr(args, 'status_path', None) or p.HERE/('delivery_status.json' if scope == 'batch_01' else f'{scope}_delivery_status.json')
    identity, runtime = p.source_identity(document['source']), p.runtime_identity(model_required=any(s['mode']=='colorize' for s in shots))
    merges, seen = {}, {}
    state = {'schema_version': 1, 'scope': scope, 'pid': __import__('os').getpid(), 'quality_acceptance': 'pending',
        'source_frames': document['source']['frame_count'], 'selected_frames': sum(shot['frames'] for shot in shots),
        'merge_registry': {}}

    def update(**details):
        state.update(details, updated_at=p.utc())
        state['merged_frames'] = sum(item['frames'] for item in merges.values())
        state['merge_registry'] = {key: {field: value.get(field) for field in ['output', 'output_sha256', 'start_frame', 'end_frame',
            'frames', 'model_attempt', 'status', 'exact_source_y', 'full_decode_verified', 'base_output', 'base_output_sha256', 'chroma_treatment_receipt',
            'scientific_screen_scene_id', 'scientific_mask_receipt', 'exact_source_uv_inside_mask', 'exact_prediction_uv_outside_mask']} for key, value in merges.items()}
        p.atomic_json(status_path, state)

    while True:
        with p.ExclusiveLock(p.HERE/'delivery_queue.lock', wait=getattr(args, 'wait_for_queue', False)):
            if p.STOP.exists():
                update(stage='stopped_at_delivery_boundary')
                return
            publication_pending = {}
            state['reference_publication_pending'] = publication_pending
            masks_pending = {}
            state['scientific_masks_pending'] = masks_pending
            for shot in shots:
                try:
                    attempt = choose_attempt(shot, identity, runtime)
                except p.ReferencePublicationPending as error:
                    publication_pending[shot['id']] = str(error)
                    merges.pop(shot['id'], None)
                    continue
                if attempt is None:
                    merges.pop(shot['id'], None)
                    continue
                try:
                    mask_config = sm.load(shot, document['source'], identity)
                except sm.ScientificMaskPending as error:
                    masks_pending[shot['id']] = str(error)
                    merges.pop(shot['id'], None)
                    continue
                token = (attempt['attempt'], attempt['output_sha256'], mask_config['content_digest'] if mask_config else None)
                if seen.get(shot['id']) == token and shot['id'] in merges:
                    continue
                update(stage='merging_shot', shot_id=shot['id'], active_attempt=attempt['attempt'], phase='merge', done=0, total=shot['frames'])
                try:
                    merges[shot['id']] = reviewed_reclaimed_base(shot,attempt,identity) or merge_one(document, shot, attempt, identity, update)
                except sm.ScientificMaskPending as error:
                    masks_pending[shot['id']] = str(error)
                    merges.pop(shot['id'], None)
                    continue
                seen[shot['id']] = token
                update(stage='shot_merge_ready', shot_id=shot['id'])
                if p.STOP.exists():
                    update(stage='stopped_at_delivery_boundary')
                    return
            if len(merges) == len(shots):
                registry_path = p.HERE/'source_y_overrides.json'
                overrides = p.read_json(registry_path) if registry_path.exists() else {}
                try:
                    context = override_base_context(document, merges, overrides, identity, runtime, update)
                    selected_merges = {key: apply_source_y_override(value, overrides, context) for key, value in merges.items()}
                except p.QualityReviewRejected as error:
                    selected_merges = None
                    update(stage='waiting_for_corrected_quality_review', shot_id=None, quality_hold=str(error))
                hold = scientific_scope_hold(scope, shots, selected_merges, identity) if selected_merges else None
                if selected_merges is None:
                    pass  # Release the CPU lock below; other shots can still make progress.
                elif hold:
                    p.atomic_json(BASE/'batches'/scope/'scientific_scope_review_request.json',
                        dict(source_sha256=identity['sha256'],updated_at=p.utc(),**hold))
                    update(stage='waiting_for_scientific_composite_review',shot_id=None,scientific_scope_hold=hold)
                else:
                    merges = selected_merges
                    update(stage='assembling_scope', shot_id=None, done=0, total=state['selected_frames'])
                    result = assemble_scope(document, shots, merges, identity, scope, update)
                    update(stage='draft_scope_ready', assembly=result, shot_id=None)
                    print(json.dumps({'stage': 'draft_scope_ready', 'master': result['master'], 'preview': result['preview']}), flush=True)
                    return
            else:
                update(stage='waiting_for_verified_predictions', shot_id=None,
                    waiting_shots=[shot['id'] for shot in shots if shot['id'] not in merges],
                    reference_publication_pending=publication_pending)
        # Future batches must release this shared CPU lock while awaiting GPU
        # predictions, so an already-ready correction assembly can proceed.
        if not args.wait:
            return
        time.sleep(5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=p.DEFAULT_MANIFEST)
    parser.add_argument('--batch', default='batch_01')
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--scope', default='full', help='Name for a complete-video draft assembly')
    parser.add_argument('--wait', action='store_true')
    parser.add_argument('--wait-for-queue', action='store_true')
    parser.add_argument('--status-path', type=Path)
    args = parser.parse_args()
    if args.full:
        args.batch = None
    watch(args)
