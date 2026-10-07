"""Freeze authorized outgoing-scene inference overlaps using existing approvals."""
import copy
from pathlib import Path
import production as p

directory=p.HERE/'dissolve_overlaps'
base=p.validate_manifest(p.read_json(p.PROJECT/'scenes/first_batch_manifest.json'))
measurements=p.read_json(p.PROJECT/'scenes/qc/dissolves/source_dissolve_map.json')
specs=[(850,1479,'repair_000850_001479'),(1479,1833,'repair_001479_001833'),
    (2245,2456,'shot_002245'),(8965,9808,'shot_008965')]
jobs=[]
for start,boundary,approval_id in specs:
    transition=next(row for row in measurements['transitions'] if row['boundary_frame']==boundary)
    end=transition['support_end_frame_exclusive']
    identifier=f'overlap_{start:06d}_{end:06d}'
    jobdir=directory/identifier
    original_marker=p.PROJECT/'references'/approval_id/'refs_ready.json'
    approval=p.read_json(original_marker)
    p.atomic_json(jobdir/'inherited_approval.snapshot.json',approval)
    approval.update(shot_id=identifier,scope_extension_authorization='Root authorized two-sided per-frame dissolve repair using these existing approved guides; no new guide approval implied.',
        inherited_approval_path=str(original_marker),inherited_approval_sha256=p.sha256(original_marker),
        inference_purpose='Outgoing-scene UV hypothesis on the exact actual dissolve frames; later alpha blend is separately quality reviewed.')
    marker=jobdir/'refs_ready.json';p.atomic_json(marker,approval)
    selected=dict(id=identifier,start_frame=start,end_frame=end,end_frame_exclusive=end,frames=end-start,
        mode='colorize',batch_id='batch_01',references_ready=str(marker),boundary_frame=boundary,
        description='Authorized outgoing-scene per-frame inference overlap for measured chroma-only dissolve treatment.')
    doc=copy.deepcopy(base);shots=[];inserted=False
    for shot in doc['shots']:
        if shot['end_frame']<=start or shot['start_frame']>=end:
            shots.append(shot);continue
        if shot['start_frame']<start:
            prefix=copy.deepcopy(shot);prefix.update(id=f'unselected_before_{identifier}',end_frame=start,end_frame_exclusive=start,frames=start-shot['start_frame'])
            shots.append(prefix)
        if not inserted: shots.append(selected);inserted=True
        if shot['end_frame']>end:
            suffix=copy.deepcopy(shot);suffix.update(id=f'unselected_after_{identifier}',start_frame=end,frames=shot['end_frame']-end)
            shots.append(suffix)
    doc['shots']=shots;doc['status']='authorized_per_frame_dissolve_overlap'
    doc=p.validate_manifest(doc)
    if p.approved_references(selected) is None: raise ValueError('Inherited approval is not ready')
    manifest=jobdir/'manifest.json';p.atomic_json(manifest,doc)
    jobs.append(dict(id=identifier,manifest=str(manifest),boundary_frame=boundary,
        target_shot_id=f'shot_{boundary:06d}',start_frame=start,end_frame=end,frames=end-start))
p.atomic_json(directory/'plan.json',dict(schema_version=1,status='queued_after_batch_02',created_at=p.utc(),jobs=jobs,
    total_inference_frames=sum(job['frames'] for job in jobs),preservation='No baseline predictions overwritten; original Y and UV outside source-derived support are retained.',
    review_required=True,pending_additional_boundaries=[12405,13654]))
print(directory/'plan.json')
