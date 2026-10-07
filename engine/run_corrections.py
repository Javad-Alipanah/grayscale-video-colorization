"""Wait behind first-pass GPU work, render authorized continuous pans, project crops."""
import argparse
import json
from pathlib import Path
import subprocess
import production as p
import delivery as d

MANIFEST = p.HERE/'corrections/continuous_pans_manifest.json'
PLAN = p.HERE/'corrections/plan.json'
OVERRIDES = p.HERE/'prediction_overrides.json'


def rgb_hash(path, logfile, start=0, frames=None):
    command = [str(p.FFMPEG), '-v', 'error', '-xerror', '-threads', '2', '-filter_threads', '2', '-i', str(path), '-map', '0:v:0']
    if frames is not None:
        command += ['-vf', f'trim=start_frame={start}:end_frame={start+frames}']
    command += ['-an', '-sn', '-fps_mode', 'passthrough', '-threads', '2', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']
    return d.hash_command(command, logfile)


def project_target(document, shot, parent, parent_manifest):
    if not parent['start_frame'] <= shot['start_frame'] < shot['end_frame'] <= parent['end_frame']:
        raise ValueError('Correction projection falls outside its verified parent interval')
    fingerprint = p.json_digest({'kind': 'continuous_propagation_crop', 'parent_output_sha256': parent['output_sha256'],
        'start_frame': shot['start_frame'], 'end_frame': shot['end_frame']})
    for prior in p.all_attempts():
        if prior['shot_id'] == shot['id'] and p.reusable_attempt(prior, fingerprint):
            return prior
    versions = [int(path.name.split('_')[-1]) for path in (p.RENDER/shot['id']).glob('attempt_*') if path.name.split('_')[-1].isdigit()]
    number = max(versions, default=0)+1
    directory = p.RENDER/shot['id']/f'attempt_{number:03d}'
    directory.mkdir(parents=True, exist_ok=False)
    output = directory/'prediction_rgb_ffv1.mkv'
    local_start = shot['start_frame']-parent['start_frame']
    record = {'schema_version': 1, 'shot_id': shot['id'], 'attempt': number, 'status': 'running',
        'directory': str(directory), 'started_at': p.utc(), 'start_frame': shot['start_frame'], 'end_frame': shot['end_frame'],
        'frames': shot['frames'], 'mode': 'colorize', 'output': str(output), 'fingerprint': fingerprint,
        'output_kind': 'lossless frame crop of continuous-pan neural propagation',
        'parent_shot_id': parent['shot_id'], 'parent_attempt_path': str(Path(parent['directory'])/'attempt.json'),
        'parent_manifest_path': str(parent_manifest), 'parent_output_sha256': parent['output_sha256'],
        'parent_crop_start_frame': local_start, 'source_clip': parent['source_clip'],
        'input_start_frame': shot['start_frame']-parent['source_clip']['source_clip_start_frame'],
        'canonical_settings': p.SETTINGS,
        'reference_coordinate_scope': 'All references belong to the parent propagation interval, not this cropped delivery partition.',
        'timing_scope': 'No inference repeated for the crop; use parent attempt metrics for model timing.',
        'quality_acceptance': 'pending; artificial split and real dissolve boundaries require review'}
    p.atomic_json(directory/'attempt.json', record)
    try:
        if p.sha256(parent['output']) != parent['output_sha256']:
            raise ValueError('Parent prediction changed before correction projection')
        command = [str(p.FFMPEG), '-v', 'error', '-xerror', '-y', '-threads', '2', '-filter_threads', '2',
            '-i', parent['output'], '-map', '0:v:0', '-vf', f'trim=start_frame={local_start}:end_frame={local_start+shot["frames"]},setpts=PTS-STARTPTS',
            '-frames:v', str(shot['frames']), '-an', '-sn', '-fps_mode', 'passthrough', '-c:v', 'ffv1', '-level', '3', '-threads', '2', '-pix_fmt', 'bgr0', str(output)]
        d.run_logged(command, directory/'projection.log')
        record.update(p.verify_video(output, document['source'], shot['frames'], 'bgr0', directory))
        parent_rgb = rgb_hash(parent['output'], directory/'parent_crop_rgb.log', local_start, shot['frames'])
        projected_rgb = rgb_hash(output, directory/'projected_rgb.log')
        if parent_rgb != projected_rgb or projected_rgb['decoded_bytes'] != shot['frames']*document['source']['width']*document['source']['height']*3:
            raise ValueError('Projection changed RGB bytes or frame order')
        record.update(status='pending_quality_review', finished_at=p.utc(), command=command,
            exact_parent_rgb_crop=True, parent_crop_rgb=parent_rgb, projected_rgb=projected_rgb)
        p.atomic_json(directory/'parent_attempt.snapshot.json', parent)
        p.atomic_json(directory/'parent_manifest.snapshot.json', p.read_json(parent_manifest))
    except BaseException as error:
        record.update(status='failed', error=str(error), finished_at=p.utc())
        raise
    finally:
        p.atomic_json(directory/'attempt.json', record)
    return record


def main():
    plan = p.read_json(PLAN)
    correction_doc = p.validate_manifest(p.read_json(MANIFEST))
    original_doc = p.validate_manifest(p.read_json(p.PROJECT/'scenes/first_batch_manifest.json'))
    selected = {group['id'] for group in plan['groups']}
    args = argparse.Namespace(rerender=False, reason='Repair artificial propagation resets inside continuous pans',
        wait=True, max_shots=None, wait_for_queue=True)
    plan.update(status='waiting_for_first_pass_gpu_queue', queued_at=p.utc())
    p.atomic_json(PLAN, plan)
    p.run_queue(args, correction_doc, selected)
    if p.STOP.exists():
        return
    plan.update(status='projecting_verified_corrections')
    p.atomic_json(PLAN, plan)
    identity, runtime = p.source_identity(correction_doc['source']), p.runtime_identity()
    overrides = p.read_json(OVERRIDES) if OVERRIDES.exists() else {}
    for group in plan['groups']:
        parent_shot = next(shot for shot in correction_doc['shots'] if shot['id'] == group['id'])
        approval = p.approved_references(parent_shot)
        fingerprint = p.fingerprint(parent_shot, identity, runtime, approval)
        candidates = [attempt for attempt in p.all_attempts() if attempt['shot_id'] == group['id'] and p.reusable_attempt(attempt, fingerprint)]
        if not candidates:
            raise ValueError('Correction parent did not complete with current approved references')
        parent = max(candidates, key=lambda attempt: attempt['attempt'])
        for target in group['targets']:
            shot = next(shot for shot in original_doc['shots'] if shot['id'] == target)
            result = project_target(original_doc, shot, parent, MANIFEST)
            overrides[target] = {'status': 'active_pending_quality_review', 'attempt_path': str(Path(result['directory'])/'attempt.json'),
                'output_sha256': result['output_sha256'], 'parent_output_sha256': parent['output_sha256'],
                'reason': 'Authorized continuous-pan propagation repair; same global frame mapping.', 'published_at': p.utc()}
            p.atomic_json(OVERRIDES, overrides)
            print(json.dumps({'stage': 'verified_projection_published', 'target': target, 'attempt': result['attempt']}), flush=True)
    plan.update(status='verified_projections_published_pending_visual_review', completed_at=p.utc())
    p.atomic_json(PLAN, plan)


if __name__ == '__main__':
    from recipe_guard import require_lecture1_recipe
    require_lecture1_recipe()
    main()
