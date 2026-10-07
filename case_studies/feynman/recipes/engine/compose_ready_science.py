"""Build a ready protected transition without mutating the active GPU plan.

The ordered supervisor later resumes the same hash-keyed treatment. Both use
the identical boundary/delivery lock order, so no native media is written twice.
"""
import argparse
from pathlib import Path
import production as p
import delivery as d
import boundary_chroma as b
import scientific_mask as sm
from apply_neutral_photo_exit import source_uv_handle

def compose(plan_path,boundary):
    plan=p.read_json(plan_path);job=next(j for j in plan['jobs'] if j['boundary_frame']==boundary)
    status_path=p.HERE/f'science_incremental_{boundary:06d}_status.json'
    def status(stage,**details):p.atomic_json(status_path,dict(stage=stage,updated_at=p.utc(),boundary_frame=boundary,delivery_acceptance=False,**details))
    if not plan.get('launch_authorized') or job.get('compositor_kind')=='multi_partition_neutral_photo_entry_trial':raise ValueError('Transition requires its separate joint workflow')
    for path,expected in [(plan['canonical_manifest'],plan['canonical_manifest_sha256']),(plan['source_measurement'],plan['source_measurement_sha256'])]:
        if p.sha256(path)!=expected:raise ValueError('Frozen scientific mapping changed')
    hold=p.read_json(p.HERE/'scientific_transition_holds.json').get(str(boundary),{})
    if hold.get('status')=='source_review_pending':raise sm.ScientificMaskPending(hold['reason'])
    document=p.validate_manifest(p.read_json(plan['canonical_manifest']));identity=p.source_identity(document['source']);runtime=p.runtime_identity()
    target=next(s for s in document['shots'] if s['id']==job['incoming_shot_id']);outgoing=next(s for s in document['shots'] if s['id']==job['outgoing_shot_id'])
    try:
        for side in [target,outgoing]:sm.load(side,document['source'],identity)
        context=hypothesis=overlap_attempt=None
        if job['inference_frames']:
            if p.sha256(job['manifest'])!=job['manifest_sha256']:raise ValueError('Frozen outgoing hypothesis changed')
            context=p.validate_manifest(p.read_json(job['manifest']));hypothesis=next(s for s in context['shots'] if s['id']==job['id'])
            sm.load(hypothesis,context['source'],identity)
            overlap_attempt=d.choose_attempt(hypothesis,identity,runtime)
            if overlap_attempt is None:status('waiting_for_verified_outgoing_context');return
        status('waiting_for_shared_native_delivery_lock')
        with p.ExclusiveLock(p.HERE/'boundary_chroma.lock',wait=True),p.ExclusiveLock(p.HERE/'delivery_queue.lock',wait=True):
            callback=lambda **v:status('compositing_protected_transition',**v)
            attempts=[d.choose_attempt(side,identity,runtime) for side in [target,outgoing]]
            if any(a is None for a in attempts):raise ValueError('Canonical original-Y baseline is unavailable')
            bases=[d.merge_one(document,side,attempt,identity,callback) for side,attempt in zip([target,outgoing],attempts)]
            overlap=d.merge_one(context,hypothesis,overlap_attempt,identity,callback) if hypothesis else source_uv_handle(document,outgoing,job['transition'],attempts[1],identity,callback=status)
            record,receipt=b.repair(document,target,outgoing,bases[0],bases[1],job['transition'],p.read_json(plan['source_measurement']),Path(plan['source_measurement']),overlap=overlap)
            p.reject_failed_chroma_review(target['id'],record['output_sha256'])
            registry_path=p.HERE/'source_y_overrides.json';registry=p.read_json(registry_path)
            registry[target['id']]=dict(receipt=str(receipt),output_sha256=record['output_sha256'],base_output_sha256=record['base_output_sha256'],
                status='active_pending_quality_review',support_start_frame=job['support_half_open'][0],support_end_frame_exclusive=job['support_half_open'][1])
            p.atomic_json(registry_path,registry)
        status('draft_treatment_ready_pending_native_review',receipt=str(receipt),output_sha256=record['output_sha256'])
    except sm.ScientificMaskPending as error:status('waiting_for_native_scene_masks',reason=str(error))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--plan',type=Path,default=p.HERE/'science_post_primary/plan.json');parser.add_argument('--boundary',type=int,required=True)
    args=parser.parse_args();compose(args.plan,args.boundary)
