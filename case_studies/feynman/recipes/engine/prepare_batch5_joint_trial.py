"""Freeze the reviewed four-frame source-photo entry across canonical split59059."""
import production as p
import paired_neutral_entry as joint

path=p.HERE/'science_batch05/joint_059058_059062.json'
if path.exists():
    raise ValueError('Frozen joint configuration exists; do not overwrite')
queue=p.read_json(p.HERE/'science_batch05/plan.json')
context=next(j for j in queue['jobs'] if j['id']=='science_overlap_058480_059062')
manifest=p.HERE/'final_assembly/manifest_v01.json'
document=p.validate_manifest(p.read_json(manifest))
names=['shot_058480','shot_059059']
shots=[next(s for s in document['shots'] if s['id']==name) for name in names]
review=p.read_json(context['source_review'])
if p.sha256(context['source_review'])!=context['source_review_sha256']:
    raise ValueError('Reviewed scientific source timing changed')
alpha=joint.measured_alpha(review,shots)
if list(alpha)!=list(range(59058,59062)):
    raise ValueError('The frozen joint support differs from source review')
record=dict(schema_version=1,status='queued_pending_protected_context_and_cross_batch_entry',launch_authorized=True,
    created_at=p.utc(),canonical_manifest=str(manifest),canonical_manifest_sha256=p.sha256(manifest),
    shot_ids=names,required_prior_entry_boundary=58480,nominal_boundary=59059,
    status_path=str(p.HERE/'joint_batch5_first_trial_status.json'),
    review_marker=str(p.PROJECT/'scenes/qc/dissolves/batch_05/shot_059059/joint_color_review.json'),
    job=dict(id=context['id'],manifest=context['manifest'],manifest_sha256=context['manifest_sha256'],
        compositor_kind='multi_partition_neutral_photo_entry_trial',source_onset_review=context['source_review'],
        source_onset_review_sha256=context['source_review_sha256']),
    source_support_half_open=[59058,59062],canonical_split_preserved=59059,delivery_acceptance=False,
    review_contract=dict(status='local_joint_transition_pass',joint_trial_sha256='exact published joint_trial.json SHA256',
        output_sha256={name:'exact corresponding native output SHA256' for name in names},
        exact_source_y=True,exact_outside_support_uv=True),
    outstanding_prerequisite='Source-reviewed, protected cross-batch58480 entry treatment must exist before adding its disjoint tail. No boundary is inferred.')
p.atomic_json(path,record)
print(str(path))
