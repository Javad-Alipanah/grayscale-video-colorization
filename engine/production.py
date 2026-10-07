"""Resumable frame-exact Lecture 1 production queue, using the unchanged pilot runner.

Readiness is a per-shot, explicit, hash-bound approval. Rendered predictions always
wait for quality review; they are resumable but are not automatically accepted.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
import time
import uuid

from config import CODE_DIR, PROJECT, WORKSPACE, PYTHON, RUNNER, REPO, FFMPEG, FFPROBE, GPU_LOCK
HERE = PROJECT / 'engine'  # State directory, deliberately independent of code.
RENDER = PROJECT / 'render'
DEFAULT_MANIFEST = PROJECT / 'scenes/manifest.json'
STATUS_PATH = HERE / 'status.json'
STOP = HERE / 'STOP.json'
SETTINGS = {'model': 'CMNET2 DINOv3 p374099', 'precision': 'float32',
    'max_side': 512, 'top_k': 30, 'mem_every': 5, 'disable_autotune': True,
    'proximity_bias': False, 'fresh_process_per_shot': True}


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def json_digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


class QualityReviewRejected(ValueError):
    """A verified draft is explicitly held by a hash-bound quality review."""


def reject_failed_chroma_review(shot_id, output_sha256):
    """A fresh registry pointer cannot revive an independently rejected payload."""
    path = PROJECT/'scenes/qc/dissolves/corrections'/shot_id/output_sha256[:12]/'visual_review.json'
    if path.exists():
        review = read_json(path)
        status = review.get('status', '')
        rejected = status.startswith('changes_required') or status.endswith(('_reject', '_rejected'))
        if (review.get('shot_id') == shot_id and review.get('output_sha256') == output_sha256 and rejected):
            raise QualityReviewRejected(f'Chroma payload was rejected by independent native QA: {path}')


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    # Windows readers (including PowerShell and virus scanners) can briefly open
    # an existing checkpoint without FILE_SHARE_DELETE. Keep the already-fsynced
    # replacement intact and retry only this rename, with a finite wait budget.
    for attempt in range(20):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 19:
                raise  # Old checkpoint + complete temporary receipt remain recoverable.
            time.sleep(min(.025 * (2 ** attempt), .25))


def resolve(path):
    path = Path(path)
    return path.resolve() if path.is_absolute() else (WORKSPACE / path).resolve()


class ExclusiveLock:
    """OS-backed advisory lock: auto-released on crash; the file is retained."""
    def __init__(self, path, wait=False):
        self.path = Path(path)
        self.stream = None
        self.wait = wait

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('a+b')
        if self.path.stat().st_size == 0:
            self.stream.write(b'0')
            self.stream.flush()
        self.stream.seek(0)
        announced = False
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if not self.wait or STOP.exists():
                    self.stream.close()
                    raise RuntimeError('Another production worker holds the single-GPU queue lock')
                if not announced:
                    print(json.dumps({'stage': 'waiting_for_gpu_queue', 'lock': str(self.path)}), flush=True)
                    announced = True
                time.sleep(5)
                self.stream.seek(0)
        return self

    def __exit__(self, *args):
        if self.stream:
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()


def validate_manifest(document):
    data = copy.deepcopy(document)
    if data.get('schema_version') != 1:
        raise ValueError('Expected manifest schema_version 1')
    source = data['source']
    source['path'] = str(resolve(source['path']))
    if not source.get('sha256') and Path(source['path']).is_file():
        source['sha256'] = sha256(source['path'])
    for key in ['frame_count', 'width', 'height', 'fps_num', 'fps_den']:
        if not isinstance(source.get(key), int) or source[key] <= 0:
            raise ValueError(f'Invalid source {key}')
    expected, seen, batches, previous_batch = 0, set(), set(), None
    for shot in data['shots']:
        identifier = shot['id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', identifier) or identifier in seen:
            raise ValueError(f'Invalid or duplicate shot id {identifier}')
        start = shot['start_frame']
        end = shot.get('end_frame', shot.get('end_frame_exclusive'))
        if not isinstance(start, int) or not isinstance(end, int) or start != expected or end <= start:
            raise ValueError(f'Shots must be contiguous and nonempty at {identifier}; expected {expected}')
        if shot.get('end_frame_exclusive', end) != end or shot.get('frames', end-start) != end-start:
            raise ValueError(f'Inconsistent frame aliases for {identifier}')
        shot.update(end_frame=end, end_frame_exclusive=end, frames=end-start)
        if shot.get('mode') not in {'colorize', 'passthrough', 'reusable_approved_master'}:
            raise ValueError(f'Explicit supported production mode required for {identifier}')
        if shot['mode'] == 'reusable_approved_master' and (not shot.get('source_asset') or not shot.get('reuse_ready')):
            raise ValueError('Approved-master reuse requires source_asset and reuse_ready')
        batch = shot.setdefault('batch_id', identifier)
        if not re.fullmatch(r'[A-Za-z0-9_-]+', batch):
            raise ValueError('Invalid batch id')
        if batch != previous_batch and batch in batches:
            raise ValueError('Each batch must contain a contiguous group of shots')
        batches.add(batch)
        previous_batch = batch
        shot.setdefault('references_ready', str(PROJECT / 'references' / identifier / 'refs_ready.json'))
        shot['_source'] = copy.deepcopy(source)
        expected = end
        seen.add(identifier)
    for pending in data.get('pending_ranges', []):
        start, end = pending['start_frame'], pending['end_frame']
        if not isinstance(start, int) or not isinstance(end, int) or start != expected or end <= start:
            raise ValueError('Pending ranges must be a contiguous nonempty tail after audited shots')
        if not pending.get('reason'):
            raise ValueError('Pending interval requires an explicit reason')
        expected = end
    if expected != source['frame_count']:
        raise ValueError(f'Full coverage mismatch: shots end {expected}, source has {source["frame_count"]}')
    return data


class ReferencePublicationPending(ValueError):
    """A guide publication is incomplete; strict validation still rejects it."""


def approved_references(shot):
    if shot['mode'] == 'passthrough':
        return {'marker': None, 'approval': {'status': 'passthrough'}, 'references': []}
    if shot['mode'] == 'reusable_approved_master':
        marker = resolve(shot['reuse_ready'])
        if not marker.exists():
            return None
        proof = read_json(marker)
        if proof.get('status') != 'approved':
            return None
        if proof.get('schema_version') != 1 or proof.get('shot_id') != shot['id'] or not proof.get('approved_by') or not proof.get('approved_at'):
            raise ValueError('Reuse approval scope or attribution is invalid')
        if (proof.get('start_frame'), proof.get('end_frame'), proof.get('frames')) != (shot['start_frame'], shot['end_frame'], shot['frames']):
            raise ValueError('Reuse approval frame range differs from manifest')
        asset = resolve(shot['source_asset']['path'])
        if asset != resolve(proof['asset_path']) or sha256(asset) != proof.get('asset_sha256'):
            raise ValueError('Reuse asset checksum or path changed')
        if not proof.get('source_sha256') or not proof.get('exact_decoded_y') or not proof.get('source_y_sha256') or proof['source_y_sha256'] != proof.get('asset_y_sha256'):
            raise ValueError('Reuse requires verified exact source luminance equality')
        return {'marker': str(marker), 'approval': proof, 'references': [], 'reuse': proof}
    marker = resolve(shot['references_ready'])
    if not marker.exists():
        return None
    try:
        approval = read_json(marker)
    except (FileNotFoundError, PermissionError, json.JSONDecodeError) as error:
        raise ReferencePublicationPending(f'Reference approval is being published: {marker}') from error
    if approval.get('status') != 'approved':
        return None
    if approval.get('schema_version') != 1 or approval.get('shot_id') != shot['id']:
        raise ValueError(f'Wrong readiness scope: {marker}')
    if not approval.get('approved_by') or not approval.get('approved_at'):
        raise ValueError(f'Approval attribution and timestamp required: {marker}')
    items = approval.get('references')
    if not isinstance(items, list) or not items:
        raise ValueError(f'Approved marker has no references: {marker}')
    references = []
    for item in items:
        path = resolve(item['path'])
        frame = item.get('source_frame')
        if not isinstance(frame, int) or not shot['start_frame'] <= frame < shot['end_frame']:
            raise ValueError(f'Reference source frame outside shot {shot["id"]}: {frame}')
        if not item.get('view') or not isinstance(item.get('materials'), list) or not item['materials']:
            raise ValueError(f'Reference must describe compatible view and materials: {path}')
        if path.suffix.lower() != '.png':
            raise ValueError(f'Reference must be an existing native PNG: {path}')
        try:
            digest = sha256(path)
        except (FileNotFoundError, PermissionError) as error:
            raise ReferencePublicationPending(f'Approved reference is unavailable during publication: {path}') from error
        if item.get('sha256') != digest:
            raise ReferencePublicationPending(f'Approved reference checksum mismatch: {path}')
        references.append(dict(item, path=str(path), local_frame=frame-shot['start_frame']))
    if len({r['local_frame'] for r in references}) != len(references):
        raise ValueError('Duplicate approved reference frame')
    from reference_provenance import validate_marker
    validate_marker(shot, shot.get('_source'), approval, WORKSPACE)
    return {'marker': str(marker), 'approval': approval,
        'references': sorted(references, key=lambda r: r['local_frame'])}


def probe(path, count=False):
    command = [str(FFPROBE), '-v', 'error', '-select_streams', 'v:0']
    if count:
        command.append('-count_frames')
    return json.loads(subprocess.check_output(command + ['-show_streams', '-of', 'json', str(path)]))['streams'][0]


def verify_video(path, source, frames, pixel_format, log_dir):
    stream = probe(path, count=True)
    expected = (frames, source['width'], source['height'], Fraction(source['fps_num'], source['fps_den']), pixel_format, 'ffv1')
    actual = (int(stream.get('nb_read_frames', -1)), stream['width'], stream['height'],
        Fraction(stream['r_frame_rate']), stream['pix_fmt'], stream['codec_name'])
    if actual != expected:
        raise ValueError(f'Video verification mismatch for {path}: {actual} != {expected}')
    with (Path(log_dir) / 'decode_verify.log').open('w') as log:
        subprocess.run([str(FFMPEG), '-v', 'error', '-xerror', '-i', str(path),
            '-map', '0:v:0', '-f', 'null', '-'], stdout=log, stderr=log, check=True)
    return {'verified_decoded_frames': frames, 'full_decode_verified': True, 'output_sha256': sha256(path)}


def file_identity(path):
    path = resolve(path)
    stat = path.stat()
    return {'path': str(path), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'sha256': sha256(path)}


def source_identity(source):
    path = Path(source['path'])
    stat = path.stat()
    cache = HERE / 'source_identity.json'
    if cache.exists():
        saved = read_json(cache)
        if saved['path'] == str(path) and saved['bytes'] == stat.st_size and saved['mtime_ns'] == stat.st_mtime_ns:
            if source.get('sha256') and source['sha256'] != saved['sha256']:
                raise ValueError('Source checksum differs from manifest')
            return saved
    stream = probe(path)
    if (stream['width'], stream['height'], Fraction(stream['r_frame_rate']), stream['pix_fmt']) != (
            source['width'], source['height'], Fraction(source['fps_num'], source['fps_den']), source['pixel_format']):
        raise ValueError('Source geometry, cadence or pixel format changed')
    identity = file_identity(path)
    if source.get('sha256') and source['sha256'] != identity['sha256']:
        raise ValueError('Source checksum differs from manifest')
    identity['probe'] = stream
    atomic_json(cache, identity)
    return identity


def runtime_identity(model_required=True):
    if not model_required:
        files=[{'path':str(Path(__file__)),'sha256':sha256(Path(__file__))}]
        return {'settings':SETTINGS,'files':files,'digest':json_digest(files),'model_required':False,
            'orchestrator_sha256':sha256(Path(__file__))}
    paths = [RUNNER, RUNNER.parent / 'spatial_correlation_sampler.py'] + sorted((REPO / 'colormnet').rglob('*.py'))
    paths += [REPO / 'colormnet/models.json', REPO / 'weights/DINOv3FeatureV6_LocalAtten_p374099.pth',
        REPO / 'weights/dinov3-vitb16/model.safetensors',
        REPO / 'models/checkpoints/resnet18-5c106cde.pth', REPO / 'models/checkpoints/resnet50-19c8e357.pth']
    config = read_json(REPO / 'colormnet/models.json')['cmnet2']['dinov3']
    if config['checkpoint'] != 'DINOv3FeatureV6_LocalAtten_p374099.pth' or config['weights_dir'] != 'dinov3-vitb16':
        raise ValueError('Canonical DINOv3 model configuration changed')
    files = [{'path': str(path), 'sha256': sha256(path)} for path in paths]
    return {'settings': SETTINGS, 'files': files, 'digest': json_digest(files),
        'orchestrator_sha256': sha256(Path(__file__))}


def fingerprint(shot, source, runtime, approval):
    content = {'source_sha256': source['sha256'], 'start_frame': shot['start_frame'],
        'end_frame': shot['end_frame'], 'mode': shot['mode'], 'settings': SETTINGS,
        'runtime': runtime['digest'] if shot['mode'] == 'colorize' else 'source-passthrough',
        'references': approval['references']}
    if approval.get('reuse'):
        content['reuse'] = {key: approval['reuse'][key] for key in
            ['asset_sha256', 'source_sha256', 'source_y_sha256', 'asset_y_sha256']}
    return json_digest(content)


def reusable_attempt(attempt, expected_fingerprint):
    if attempt.get('status') not in {'pending_quality_review', 'accepted'}:
        return False
    if attempt.get('fingerprint') != expected_fingerprint or not attempt.get('full_decode_verified'):
        return False
    if attempt.get('verified_decoded_frames') != attempt.get('frames'):
        return False
    output = Path(attempt.get('output', ''))
    return output.is_file() and sha256(output) == attempt.get('output_sha256')


def all_attempts():
    return [read_json(path) for path in sorted(RENDER.glob('*/attempt_*/attempt.json'))]


def apply_quality_review(attempt_path, review):
    attempt_path = Path(attempt_path)
    record = read_json(attempt_path)
    if (review.get('shot_id'), review.get('attempt')) != (record['shot_id'], record['attempt']):
        raise ValueError('Quality review names a different attempt')
    if record['status'] not in {'pending_quality_review', 'accepted', 'rejected'} or not record.get('full_decode_verified'):
        raise ValueError('Only stream-verified completed outputs can be reviewed')
    if review.get('status') not in {'accepted', 'rejected'} or not all(review.get(key) for key in ['reviewed_by', 'reviewed_at', 'notes']):
        raise ValueError('Explicit acceptance/rejection with attribution, time and notes is required')
    if review.get('output_sha256') != record['output_sha256'] or sha256(record['output']) != record['output_sha256']:
        raise ValueError('Quality review output hash mismatch')
    review_path = attempt_path.parent / ('quality_review_' + uuid.uuid4().hex + '.json')
    atomic_json(review_path, review)
    record.update(status=review['status'], quality_review_path=str(review_path), quality_review=review)
    atomic_json(attempt_path, record)
    return record


def publish(document, selected, stage, active=None, note=None):
    attempts = all_attempts()
    shots = []
    for shot in document['shots']:
        matching = [a for a in attempts if a['shot_id'] == shot['id']
            and a['start_frame'] == shot['start_frame'] and a['end_frame'] == shot['end_frame']]
        valid = [a for a in matching if a['status'] in {'pending_quality_review', 'accepted'}]
        latest = max(valid, key=lambda a: a['attempt'], default=None)
        accepted = max((a for a in valid if a['status'] == 'accepted'), key=lambda a: a['attempt'], default=None)
        shots.append({**{key: shot[key] for key in ['id', 'start_frame', 'end_frame', 'frames', 'mode', 'batch_id']},
            'status': latest['status'] if latest else 'awaiting_references',
            'latest_valid_attempt': latest, 'accepted_attempt': accepted})
    record = {'schema_version': 1, 'updated_at': utc(), 'pid': os.getpid(), 'stage': stage,
        'active': active, 'note': note, 'stop_requested': STOP.exists(), 'selected_shots': sorted(selected),
        'source': document['source'], 'expected_frames': document['source']['frame_count'],
        'rendered_frames': sum(s['frames'] for s in shots if s['latest_valid_attempt']),
        'accepted_frames': sum(s['frames'] for s in shots if s['accepted_attempt']),
        'selected_expected_frames': sum(s['frames'] for s in shots if s['id'] in selected),
        'selected_rendered_frames': sum(s['frames'] for s in shots if s['id'] in selected and s['latest_valid_attempt']),
        'selected_accepted_frames': sum(s['frames'] for s in shots if s['id'] in selected and s['accepted_attempt']),
        'pending_ranges': document.get('pending_ranges', []),
        'all_accepted': not document.get('pending_ranges') and all(s['accepted_attempt'] for s in shots), 'shots': shots}
    atomic_json(STATUS_PATH, record)
    return record


def prepare_batch(document, batch_id, identity):
    shots = [s for s in document['shots'] if s['batch_id'] == batch_id]
    start, end = shots[0]['start_frame'], shots[-1]['end_frame']
    key = json_digest({'source': identity['sha256'], 'start': start, 'end': end})[:12]
    directory = RENDER / 'source_batches' / f'{batch_id}_{key}'
    directory.mkdir(parents=True, exist_ok=True)
    # Independent CPU preparation may run ahead of the GPU queue. This narrower
    # lock prevents duplicate writes when the renderer reaches the same batch.
    with ExclusiveLock(directory / 'source_preparation.lock', wait=True):
        return prepare_batch_locked(document, batch_id, identity, directory, start, end)


def prepare_batch_locked(document, batch_id, identity, directory, start, end):
    marker = directory / 'source_mapping.json'
    if marker.exists():
        existing = read_json(marker)
        if existing.get('status') == 'complete' and Path(existing['path']).exists() and sha256(existing['path']) == existing['sha256']:
            return existing
    output = directory / 'source_ffv1.mkv'
    # Frame trim is indexed against the original decoder, never a rounded timestamp.
    command = [str(FFMPEG), '-v', 'error', '-xerror', '-y', '-i', identity['path'], '-map', '0:v:0',
        '-vf', f'trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS',
        '-frames:v', str(end-start), '-fps_mode', 'passthrough', '-an', '-sn',
        '-c:v', 'ffv1', '-level', '3', '-pix_fmt', document['source']['pixel_format'], str(output)]
    began = time.perf_counter()
    print(json.dumps({'stage': 'prepare_batch', 'batch_id': batch_id, 'start_frame': start, 'end_frame': end}), flush=True)
    with (directory / 'extract.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=log, check=True)
    validation = verify_video(output, document['source'], end-start, document['source']['pixel_format'], directory)
    result = {'status': 'complete', 'path': str(output), 'sha256': validation['output_sha256'],
        'source_sha256': identity['sha256'], 'source_path': identity['path'], 'batch_id': batch_id,
        'source_clip_start_frame': start, 'source_clip_end_frame': end,
        'frames': end-start, 'command': command, 'pixel_format': document['source']['pixel_format'],
        'global_frame_rule': 'source_global_frame = source_clip_start_frame + decoded_clip_frame',
        'full_decode_verified': True, 'wall_seconds': time.perf_counter()-began, 'completed_at': utc()}
    atomic_json(marker, result)
    return result


def gpu_compute_conflicts(output, windows):
    lines = [line for line in output.splitlines() if line.strip()]
    if not windows:
        return lines
    # WDDM exposes graphics applications in query-compute-apps (even Explorer).
    # The OS queue lock is authoritative for this pipeline. Also reject active
    # Python/model/render processes which could be orphaned or launched elsewhere.
    result = []
    for line in lines:
        name = PureWindowsPath(line.split(',', 1)[-1].strip()).name.lower()
        if name.startswith(('python', 'ollama', 'llama', 'comfy')) or name in {'blender.exe', 'ffmpeg.exe'}:
            result.append(line)
    return result


def assert_gpu_idle():
    result = subprocess.run(['nvidia-smi', '--query-compute-apps=pid,process_name', '--format=csv,noheader'],
        capture_output=True, text=True, check=True)
    lines = gpu_compute_conflicts(result.stdout, windows=os.name == 'nt')
    # Independent applications are resource observations, not permission gates.
    # Refuse only another instance of this exact inference runner, including an
    # orphan which outlived its queue process after a crash.
    if os.name == 'nt':
        query = "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
        processes = json.loads(subprocess.check_output(['powershell.exe', '-NoProfile', '-NonInteractive',
            '-Command', query], text=True) or '[]')
        processes = [processes] if isinstance(processes, dict) else processes
        for process in processes:
            command = (process.get('CommandLine') or '').replace('\\', '/').lower()
            if str(RUNNER).replace('\\', '/').lower() in command:
                raise RuntimeError(f'Another CMNET2 pilot runner is active (PID {process["ProcessId"]})')
    memory = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.free,memory.total,utilization.gpu',
        '--format=csv,noheader,nounits'], text=True).strip()
    observation = {'observed_at': utc(), 'other_compute_processes': lines,
        'gpu_free_total_mib_utilization_percent': memory,
        'policy': 'One CMNET2 queue/runner; other applications are observed without modification.'}
    atomic_json(HERE / 'gpu_observation.json', observation)
    return observation


def run_attempt(document, shot, identity, runtime, approval, clip, selected, reason):
    versions = [int(path.name.split('_')[-1]) for path in (RENDER / shot['id']).glob('attempt_*')
        if path.is_dir() and path.name.split('_')[-1].isdigit()]
    version = max(versions, default=0)+1
    directory = RENDER / shot['id'] / f'attempt_{version:03d}'
    directory.mkdir(parents=True, exist_ok=False)
    atomic_json(directory / 'attempt.json', {'schema_version': 1, 'shot_id': shot['id'],
        'attempt': version, 'status': 'preparing', 'directory': str(directory), 'started_at': utc(),
        'start_frame': shot['start_frame'], 'end_frame': shot['end_frame'], 'frames': shot['frames']})
    try:
        return execute_attempt(document, shot, identity, runtime, approval, clip, selected, reason, version, directory)
    except BaseException as error:
        record = read_json(directory / 'attempt.json')
        if record['status'] != 'failed':
            record.update(status='failed', finished_at=utc(), error=str(error))
            atomic_json(directory / 'attempt.json', record)
        raise


def execute_attempt(document, shot, identity, runtime, approval, clip, selected, reason, version, directory):
    if shot['mode'] == 'reusable_approved_master':
        proof = approval['reuse']
        if proof['source_sha256'] != identity['sha256']:
            raise ValueError('Reuse proof names a different original source file')
        output = resolve(proof['asset_path'])
        atomic_json(directory / 'reuse.snapshot.json', proof)
        atomic_json(directory / 'manifest.snapshot.json', document)
        stream = probe(output)
        verified = verify_video(output, document['source'], shot['frames'], stream['pix_fmt'], directory)
        record = {'schema_version': 1, 'shot_id': shot['id'], 'attempt': version,
            'status': 'pending_quality_review', 'mode': shot['mode'], 'directory': str(directory),
            'start_frame': shot['start_frame'], 'end_frame': shot['end_frame'], 'frames': shot['frames'],
            'output': str(output), 'output_kind': 'existing approved source-Y master, referenced without copying',
            'fingerprint': fingerprint(shot, identity, runtime, approval), 'reuse_proof': proof,
            'join_review_required': True, 'finished_at': utc(), **verified}
        atomic_json(directory / 'attempt.json', record)
        return record
    refdir = directory / 'approved_references'
    refdir.mkdir()
    for ref in approval['references']:
        from PIL import Image
        frozen = refdir / f'ref_{ref["local_frame"]:06d}.png'
        try:
            shutil.copy2(ref['path'], frozen)
        except (FileNotFoundError, PermissionError) as error:
            raise ReferencePublicationPending('Reference changed while freezing approval snapshot') from error
        if sha256(frozen) != ref['sha256']:
            raise ReferencePublicationPending('Reference changed while freezing approval snapshot')
        with Image.open(frozen) as image:
            if image.size != (document['source']['width'], document['source']['height']):
                raise ValueError(f'Approved reference must use native source geometry: {ref["path"]} has {image.size}')
    atomic_json(directory / 'refs_ready.snapshot.json', approval)
    atomic_json(directory / 'runtime.snapshot.json', runtime)
    atomic_json(directory / 'manifest.snapshot.json', document)
    local_start = shot['start_frame'] - clip['source_clip_start_frame']
    if shot['mode'] == 'colorize':
        output = directory / 'prediction_rgb_ffv1.mkv'
        command = [str(PYTHON), str(RUNNER), '--input', clip['path'], '--refs', str(refdir),
            '--output-dir', str(directory), '--start-frame', str(local_start), '--frames', str(shot['frames']),
            '--max-side', '512', '--top-k', '30', '--disable-autotune']
        gpu_observation = assert_gpu_idle()
    else:
        output = directory / 'source_passthrough_ffv1.mkv'
        command = [str(FFMPEG), '-v', 'error', '-xerror', '-y', '-i', clip['path'], '-map', '0:v:0',
            '-vf', f'trim=start_frame={local_start}:end_frame={local_start+shot["frames"]},setpts=PTS-STARTPTS',
            '-frames:v', str(shot['frames']), '-fps_mode', 'passthrough', '-an', '-sn',
            '-c:v', 'ffv1', '-level', '3', '-pix_fmt', document['source']['pixel_format'], str(output)]
    record = {'schema_version': 1, 'shot_id': shot['id'], 'attempt': version, 'status': 'running',
        'started_at': utc(), 'start_frame': shot['start_frame'], 'end_frame': shot['end_frame'],
        'frames': shot['frames'], 'mode': shot['mode'], 'source_clip': clip,
        'input_start_frame': local_start, 'fingerprint': fingerprint(shot, identity, runtime, approval),
        'output': str(output), 'directory': str(directory), 'command': command, 'reason': reason,
        'references': approval['references'], 'canonical_settings': SETTINGS,
        'review_policy': 'Stream validity permits resume; separate explicit quality acceptance is required.'}
    if shot['mode'] == 'colorize':
        record['gpu_admission_observation'] = gpu_observation
    atomic_json(directory / 'attempt.json', record)
    started = time.perf_counter()
    print(json.dumps({'stage': 'shot_start', 'shot_id': shot['id'], 'attempt': version, 'frames': shot['frames']}), flush=True)
    try:
        with (directory / 'runner.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            record['worker_pid'] = process.pid
            atomic_json(directory / 'attempt.json', record)
            while process.poll() is None:
                progress = {'shot_id': shot['id'], 'attempt': version, 'worker_pid': process.pid,
                    'elapsed_seconds': round(time.perf_counter()-started, 1)}
                # The runner reports every 24 frames; tail only, without reading a growing log in full.
                try:
                    with (directory / 'runner.log').open('rb') as reader:
                        reader.seek(max(0, reader.seek(0, 2)-16000))
                        lines = reader.read().decode('utf-8', errors='replace').splitlines()
                    for line in reversed(lines):
                        if line.startswith('{'):
                            candidate = json.loads(line)
                            if candidate.get('stage') in {'render', 'initialize'}:
                                progress['runner'] = candidate
                                break
                except (OSError, ValueError):
                    pass
                publish(document, selected, 'rendering', progress)
                time.sleep(5)
            record['returncode'] = process.returncode
        if process.returncode:
            raise RuntimeError(f'Shot runner failed ({process.returncode}); see {directory / "runner.log"}')
        if shot['mode'] == 'colorize':
            metrics = read_json(directory / 'metrics.json')
            settings = metrics['settings']
            if metrics['frames'] != shot['frames'] or metrics['input_start_frame'] != local_start:
                raise ValueError('Runner frame range differs from mapped source interval')
            if (settings['top_k'], settings['mem_every'], settings['proximity_bias'], settings['cudnn_benchmark']) != (30, 5, False, False):
                raise ValueError('Runner settings differ from canonical configuration')
            record['metrics_path'] = str(directory / 'metrics.json')
            for key in ['render_seconds', 'initialization_seconds', 'inference_seconds', 'render_fps', 'inference_fps', 'peak_torch_allocated_mib']:
                record[key] = metrics[key]
        record.update(verify_video(output, document['source'], shot['frames'],
            'bgr0' if shot['mode'] == 'colorize' else document['source']['pixel_format'], directory))
        if shot['mode'] == 'colorize' and record['output_sha256'] != metrics['output_sha256']:
            raise ValueError('Prediction differs from runner output checksum')
        record['status'] = 'pending_quality_review'
    except BaseException as error:
        record.update(status='failed', error=str(error))
        raise
    finally:
        record.update(finished_at=utc(), wall_seconds=time.perf_counter()-started)
        atomic_json(directory / 'attempt.json', record)
    print(json.dumps({'stage': 'shot_complete', 'shot_id': shot['id'], 'attempt': version,
        'status': record['status'], 'frames': shot['frames'], 'wall_seconds': record['wall_seconds']}), flush=True)
    return record


def run_queue(args, document, selected):
    with ExclusiveLock(GPU_LOCK, wait=getattr(args, 'wait_for_queue', False)):
        publish(document, selected, 'initializing')
        identity = source_identity(document['source'])
        runtime = runtime_identity(model_required=any(s['mode']=='colorize' for s in document['shots'] if s['id'] in selected))
        completed, clip_cache = set(), {}
        # Interrupted records are preserved and never treated as completed.
        for attempt in all_attempts():
            if attempt['status'] in {'running', 'preparing'}:
                attempt.update(status='interrupted', interrupted_at=utc())
                atomic_json(Path(attempt['directory']) / 'attempt.json', attempt)
        while True:
            if STOP.exists():
                publish(document, selected, 'stopped', note='Stop flag honored at shot boundary; remove STOP.json to resume.')
                break
            pending = [s for s in document['shots'] if s['id'] in selected and s['id'] not in completed]
            if not pending:
                publish(document, selected, 'queue_complete')
                break
            runnable = None
            publication_pending = {}
            for shot in pending:
                try:
                    approval = approved_references(shot)
                except ReferencePublicationPending as error:
                    publication_pending[shot['id']] = str(error)
                    continue
                if approval is None:
                    continue
                if approval.get('reuse') and approval['reuse']['source_sha256'] != identity['sha256']:
                    raise ValueError('Reuse proof source checksum differs from original source')
                fp = fingerprint(shot, identity, runtime, approval)
                prior = sorted((a for a in all_attempts() if a['shot_id'] == shot['id']), key=lambda a: a['attempt'], reverse=True)
                if not args.rerender and any(reusable_attempt(a, fp) for a in prior):
                    completed.add(shot['id'])
                    print(json.dumps({'stage': 'resume_skip', 'shot_id': shot['id']}), flush=True)
                    continue
                runnable = (shot, approval)
                break
            if runnable is None:
                if all(s['id'] in completed for s in pending):
                    continue
                publish(document, selected, 'waiting_for_references',
                    note=json.dumps({'reference_publication_pending': publication_pending}) if publication_pending else None)
                if not args.wait:
                    break
                time.sleep(5)
                continue
            shot, approval = runnable
            batch = shot['batch_id']
            if shot['mode'] != 'reusable_approved_master' and batch not in clip_cache:
                publish(document, selected, 'preparing_batch', {'batch_id': batch})
                clip_cache[batch] = prepare_batch(document, batch, identity)
            if STOP.exists():
                continue
            try:
                run_attempt(document, shot, identity, runtime, approval, clip_cache.get(batch), selected, args.reason)
            except ReferencePublicationPending as error:
                publish(document, selected, 'waiting_for_references', note=str(error))
                if not args.wait:
                    break
                time.sleep(5)
                continue
            completed.add(shot['id'])
            if args.max_shots and len(completed) >= args.max_shots:
                publish(document, selected, 'batch_limit_reached')
                break


def main():
    global STATUS_PATH
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['validate', 'prepare', 'run', 'status', 'stop', 'resume', 'review'])
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--shot', action='append')
    parser.add_argument('--batch', action='append')
    parser.add_argument('--wait', action='store_true')
    parser.add_argument('--rerender', action='store_true')
    parser.add_argument('--reason')
    parser.add_argument('--max-shots', type=int)
    parser.add_argument('--wait-for-queue', action='store_true', help='Queue behind the active worker without changing its state')
    parser.add_argument('--attempt-file', type=Path)
    parser.add_argument('--review-file', type=Path)
    parser.add_argument('--status-path', type=Path, help='Separate progress checkpoint for this queue scope')
    args = parser.parse_args()
    if args.status_path:
        STATUS_PATH = resolve(args.status_path)
    if args.action == 'review':
        if not args.attempt_file or not args.review_file:
            raise ValueError('review requires --attempt-file and --review-file')
        result = apply_quality_review(args.attempt_file, read_json(args.review_file))
        print(json.dumps({'shot_id': result['shot_id'], 'attempt': result['attempt'], 'status': result['status']}))
        return
    if args.action == 'stop':
        atomic_json(STOP, {'requested_at': utc(), 'mode': 'after_current_shot', 'reason': args.reason})
        print('Stop requested after the current shot. Completed work remains resumable.')
        return
    if args.action == 'resume':
        STOP.unlink(missing_ok=True)
        print('Stop flag removed. Run the same queue command to resume.')
        return
    document = validate_manifest(read_json(args.manifest))
    selected = {s['id'] for s in document['shots'] if (not args.shot or s['id'] in args.shot)
        and (not args.batch or s['batch_id'] in args.batch)}
    if not selected or (args.shot and set(args.shot)-{s['id'] for s in document['shots']}):
        raise ValueError('Unknown or empty shot selection')
    if args.rerender and not args.reason:
        raise ValueError('A reason is required for a versioned rerender')
    if args.action == 'validate':
        status = [{'id': s['id'], 'frames': s['frames'], 'mode': s['mode'],
            'references_approved': approved_references(s) is not None} for s in document['shots'] if s['id'] in selected]
        print(json.dumps({'valid': True, 'source': document['source'], 'shots': status}, indent=2))
    elif args.action == 'status':
        print(json.dumps(read_json(STATUS_PATH), indent=2))
    elif args.action == 'prepare':
        with ExclusiveLock(GPU_LOCK):
            identity = source_identity(document['source'])
            for batch in dict.fromkeys(s['batch_id'] for s in document['shots'] if s['id'] in selected):
                publish(document, selected, 'preparing_batch', {'batch_id': batch})
                prepare_batch(document, batch, identity)
            publish(document, selected, 'sources_prepared')
    else:
        try:
            run_queue(args, document, selected)
        except BaseException as error:
            # A competing worker must never overwrite the active worker's checkpoint.
            if 'worker holds' not in str(error):
                publish(document, selected, 'failed', note=str(error))
            raise


if __name__ == '__main__':
    main()
