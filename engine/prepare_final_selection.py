"""Freeze current complete selected timeline for review; never encode or accept."""
from pathlib import Path
import production as p
import delivery as d

STATES = ['batch_01_remaining_repairs_delivery_status', 'batch_02_board_delivery_status',
          'batch_03_refined_v02_delivery_status', 'batch_04_delivery_status',
          'batch_05_material_delivery_status', 'batch_06_board_delivery_status']


def main():
    plan = p.read_json(p.HERE/'final_assembly/plan.json')
    manifest = Path(plan['manifest'])
    if p.sha256(manifest) != plan['manifest_sha256']:
        raise ValueError('Final manifest changed')
    document = p.validate_manifest(p.read_json(manifest))
    selected = {}; assemblies = []
    for state_name in STATES:
        path = p.HERE/(state_name+'.json'); state = p.read_json(path)
        if state['stage'] != 'draft_scope_ready':
            raise ValueError('Section is not closed: '+state_name)
        assembly = state['assembly']
        if not all(assembly.get(k) is True for k in ['exact_source_y','exact_source_pcm','full_decode_verified']):
            raise ValueError('Section internal preservation checks incomplete')
        receipt = Path(assembly['master']).parent/'assembly.json'
        disk = p.read_json(receipt)
        if disk['master_sha256'] != assembly['master_sha256']:
            raise ValueError('Section receipt differs from scoped state')
        for row in assembly['shots']:
            if row['shot_id'] in selected: raise ValueError('Duplicate shot in current section selection')
            if p.sha256(row['output']) != row['output_sha256']:
                raise ValueError('Selected shot media changed: '+row['shot_id'])
            selected[row['shot_id']] = row
        assemblies.append(dict(scope=assembly['scope'], receipt=str(receipt), receipt_sha256=p.sha256(receipt),
                               master=assembly['master'],master_sha256=assembly['master_sha256']))
    if set(selected) != {s['id'] for s in document['shots']}:
        raise ValueError('Current assembled shot set differs from frozen full manifest')
    if d.validate_merged_coverage(document['shots'],selected) != (0,80026):
        raise ValueError('Current full timeline does not cover the exact source')
    overrides = p.read_json(p.HERE/'source_y_overrides.json')
    for sid,row in selected.items():
        if sid in overrides and overrides[sid]['output_sha256'] != row['output_sha256']:
            raise ValueError('A newer selected treatment is absent from its section: '+sid)
    scope_proofs=[]
    for batch in ['batch_04','batch_05']:
        path=p.PROJECT/'scenes/qc/projection_masks'/(batch+'_delivery_ready.json')
        scoped=p.read_json(path)
        subset={s['id']:selected[s['id']]['output_sha256'] for s in document['shots'] if s['batch_id']==batch}
        if scoped['status']!='scientific_scope_review_pass' or scoped['selected_output_sha256']!=subset:
            raise ValueError('Scientific subsection scope differs')
        scope_proofs.append(dict(path=str(path),sha256=p.sha256(path)))
    hashes={s['id']:selected[s['id']]['output_sha256'] for s in document['shots']}
    fingerprint=p.json_digest(dict(manifest=p.sha256(manifest),selected=hashes))
    request=dict(schema_version=1,status='complete_current_selection_pending_material_and_full_scope_review',
        prepared_at=p.utc(),manifest=str(manifest),manifest_sha256=p.sha256(manifest),source_sha256=p.source_identity(document['source'])['sha256'],
        source_frames=80026,selected_frames=80026,selected_shots=len(selected),selected_output_sha256=hashes,
        selected_media=[dict(shot_id=s['id'],start_frame=s['start_frame'],end_frame=s['end_frame'],
                            output=selected[s['id']]['output'],output_sha256=selected[s['id']]['output_sha256']) for s in document['shots']],
        current_section_assemblies=assemblies,scientific_subsection_proofs=scope_proofs,
        auto_launch=False,delivery_acceptance=False,
        continuous_viewing_review=dict(status='deferred_to_user_by_explicit_instruction',assistant_review_performed=False,blocks_delivery=False),
        outstanding=['Remaining diagnosed material corrections and their scoped native reviews.',
                     'Fresh independent checks of any revised material section masters.',
                     'Exact full scientific-scope receipt after final selected hashes freeze.',
                     'Full master/preview construction, independent originalY/PCM/PTS/pilot identity and scoped native/transition QA.'])
    path=p.HERE/'final_assembly'/('selected_'+fingerprint[:16]+'.json')
    p.atomic_json(path,request)
    p.atomic_json(p.HERE/'final_assembly/current_selection.json',dict(path=str(path),sha256=p.sha256(path),status=request['status'],updated_at=p.utc()))
    print(str(path))


if __name__=='__main__':
    from recipe_guard import require_lecture1_recipe
    require_lecture1_recipe()
    main()
