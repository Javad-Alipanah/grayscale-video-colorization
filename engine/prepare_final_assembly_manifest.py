"""Freeze full-lecture mapping from each batch's actual production authority.

This only prepares an assembly manifest and its review requirements. It does not
launch inference, encode media, or promote a working draft.
"""
import copy
import json
import production as p


def main():
    directory = p.HERE/'final_assembly'
    target = directory/'manifest_v01.json'
    if target.exists():
        raise ValueError('Final assembly mapping already exists; version it instead of overwriting')
    authorities = [
        ('batch_01', p.PROJECT/'scenes/first_batch_manifest.json'),
        ('batch_02', p.PROJECT/'scenes/second_batch_manifest.json'),
        ('batch_03', p.HERE/'batch_03_refined_v02_manifest.json'),
        ('batch_04', p.HERE/'batch_04_manifest.json'),
        ('batch_05', p.HERE/'batch_05_manifest.json'),
        ('batch_06', p.HERE/'batch_06_manifest.json'),
    ]
    source = None
    source_keys = ['path', 'frame_count', 'fps_num', 'fps_den', 'width', 'height', 'pixel_format']
    shots, batches, proofs = [], [], []
    for batch, path in authorities:
        document = p.validate_manifest(p.read_json(path))
        if source is None:
            source = copy.deepcopy(document['source'])
        if any(document['source'][key] != source[key] for key in source_keys):
            raise ValueError(f'Frozen batch source identity differs: {batch}')
        selected = [copy.deepcopy(s) for s in document['shots'] if s['batch_id'] == batch]
        if not selected:
            raise ValueError(f'Frozen authority has no selected shots: {batch}')
        for shot in selected:
            if p.approved_references(shot) is None:
                raise ValueError(f'Unpublished approved guide set: {shot["id"]}')
        shots.extend(selected)
        batches.append(dict(id=batch, start_frame=selected[0]['start_frame'],
            end_frame=selected[-1]['end_frame'], frames=sum(s['frames'] for s in selected)))
        proofs.append(dict(batch_id=batch, manifest=str(path), manifest_sha256=p.sha256(path),
            selected_shot_ids=[s['id'] for s in selected]))
    selection_path = p.HERE/'audience_repair_v02/selection.json'
    selection = p.read_json(selection_path)
    audience = next(s for s in shots if s['id'] == 'shot_032320')
    refined = p.read_json(selection['refinement_manifest'])
    if p.sha256(selection['refinement_manifest']) != selection['refinement_manifest_sha256']:
        raise ValueError('Reviewed audience refinement authority changed')
    if audience != next(s for s in p.validate_manifest(refined)['shots'] if s['id'] == audience['id']):
        raise ValueError('Final manifest did not retain the reviewed audience mapping')
    if p.sha256(selection['review']) != selection['review_sha256']:
        raise ValueError('Audience local review changed')
    pilot = [s for s in shots if s['mode'] == 'reusable_approved_master']
    if len(pilot) != 1 or (pilot[0]['start_frame'], pilot[0]['end_frame']) != (21579, 25899):
        raise ValueError('Immutable approved pilot interval changed')
    if (shots[-1]['start_frame'], shots[-1]['end_frame'], shots[-1]['mode']) != (79665, 80026, 'passthrough'):
        raise ValueError('Final source passthrough changed')
    result = p.validate_manifest(dict(schema_version=1, status='frozen_mapping_pending_final_quality_review',
        lecture=1, source=source, shots=shots, batches=batches, pending_ranges=[],
        assembly_authorities=proofs, audience_selection=str(selection_path),
        audience_selection_sha256=p.sha256(selection_path),
        review_policy='Full coverage is a mapping proof, not visual acceptance. Scientific fields and all outstanding material/transition findings remain gated.'))
    p.atomic_json(target, result)
    plan = dict(schema_version=1, status='mapping_ready_quality_and_storage_gated', created_at=p.utc(),
        manifest=str(target), manifest_sha256=p.sha256(target), frames=80026,
        frame_range_half_open=[0, 80026], shots=len(shots), batches=batches,
        source_sha256=p.read_json(p.HERE/'batch_06_manifest.json')['source'].get('sha256'),
        final_delivery_acceptance=False, auto_launch=False,
        requirements=[
            'Complete the currently ordered final primary, batch3 per-frame repairs and protected scientific composites.',
            'Resolve or explicitly review all pending native material, title/credits, reference omissions and join findings, including pilot-entry matching.',
            'Retain the immutable approved pilot interval with all decoded Y/U/V planes unchanged.',
            'Bind independent scientific-scope review to the exact selected native shot hashes; no unprotected projection imagery may enter assembly.',
            'Recompute the final-assembly disk budget, keeping the existing 30 percent allowance and 10 GiB free reserve.',
            'After assembly independently verify all80026 originalY frames, originalPCM, every presentation timestamp, all pilot planes and scoped native/transition QA; continuous viewing is deferred to the user by explicit instruction.',
            'Keep the full master and preview as working drafts until final review; do not claim coverage as acceptance.',
        ],
        native_source_y_preservation=True, original_audio_policy='untouched decoded source PCM float32 stereo48k',
        approved_pilot_range_half_open=[21579, 25899], final_passthrough_range_half_open=[79665, 80026])
    p.atomic_json(directory/'plan.json', plan)
    print(json.dumps(dict(manifest=str(target), sha256=p.sha256(target), shots=len(shots), frames=80026,
        pending_ranges=0, auto_launch=False), indent=2))


if __name__ == '__main__':
    from recipe_guard import require_lecture1_recipe
    require_lecture1_recipe()
    main()
