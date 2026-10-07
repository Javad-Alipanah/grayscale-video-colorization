"""Prove an approved master interval matches current source Y before registering reuse.

Writes an engine-local proof; the reference owner publishes it as reuse_ready.
Boundary color review remains pending and is not implied by this pixel proof.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import production as p


def luma_hash(path, frames, start_frame=0):
    command = [str(p.FFMPEG), '-v', 'error', '-xerror', '-i', str(path), '-map', '0:v:0',
        '-vf', f'trim=start_frame={start_frame}:end_frame={start_frame+frames},setpts=PTS-STARTPTS,extractplanes=y',
        '-frames:v', str(frames), '-fps_mode', 'passthrough', '-an', '-sn',
        '-c:v', 'rawvideo', '-pix_fmt', 'gray', '-f', 'hash', '-hash', 'sha256', '-']
    value = subprocess.check_output(command, text=True).strip().removeprefix('SHA256=')
    if len(value) != 64:
        raise RuntimeError('Unexpected luma hash output')
    return value, command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=p.DEFAULT_MANIFEST)
    parser.add_argument('--shot', required=True)
    args = parser.parse_args()
    document = p.validate_manifest(p.read_json(args.manifest))
    shot = next(s for s in document['shots'] if s['id'] == args.shot)
    if shot['mode'] != 'reusable_approved_master':
        raise ValueError('Interval must explicitly request approved-master reuse')
    asset_start = shot.get('source_asset_start_frame', 0)
    if asset_start != 0:
        raise ValueError('Only a whole already-approved asset is supported; do not silently trim it')
    directory = p.HERE / 'reuse_proofs' / shot['id']
    directory.mkdir(parents=True, exist_ok=True)
    asset = p.resolve(shot['source_asset']['path'])
    started = time.perf_counter()
    identity = p.source_identity(document['source'])
    asset_stream = p.probe(asset)
    print(json.dumps({'stage': 'verify_reuse_stream', 'shot_id': shot['id'], 'frames': shot['frames']}), flush=True)
    verified = p.verify_video(asset, document['source'], shot['frames'], asset_stream['pix_fmt'], directory)
    print(json.dumps({'stage': 'hash_full_source_y', 'source_start_frame': shot['start_frame']}), flush=True)
    source_y, source_command = luma_hash(identity['path'], shot['frames'], shot['start_frame'])
    print(json.dumps({'stage': 'hash_approved_asset_y'}), flush=True)
    asset_y, asset_command = luma_hash(asset, shot['frames'])
    proof = {'schema_version': 1, 'shot_id': shot['id'], 'status': 'approved' if source_y == asset_y else 'failed',
        'approved_by': 'Previously user-approved three-minute master; exact source mapping verified by production engine',
        'approved_at': p.utc(), 'start_frame': shot['start_frame'], 'end_frame': shot['end_frame'], 'frames': shot['frames'],
        'asset_path': str(asset), 'asset_sha256': verified['output_sha256'], 'asset_pixel_format': asset_stream['pix_fmt'],
        'source_path': identity['path'], 'source_sha256': identity['sha256'],
        'source_y_sha256': source_y, 'asset_y_sha256': asset_y, 'exact_decoded_y': source_y == asset_y,
        'full_decode_verified': True, 'verified_decoded_frames': verified['verified_decoded_frames'],
        'source_luma_command': source_command, 'asset_luma_command': asset_command,
        'join_review_required': True, 'join_review_status': 'pending',
        'reuse_policy': 'Reference existing asset without copying. Ignore its audio; delivery uses original lecture audio.',
        'wall_seconds': time.perf_counter()-started}
    output = directory / 'reuse_ready.proof.json'
    p.atomic_json(output, proof)
    if source_y != asset_y:
        raise RuntimeError('Approved master Y does not match this source range; reuse refused')
    print(json.dumps({'status': 'verified', 'proof': str(output), 'frames': shot['frames'],
        'exact_decoded_y': True, 'wall_seconds': proof['wall_seconds']}, indent=2))


if __name__ == '__main__':
    main()
