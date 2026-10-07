"""Run mapped batch2 overlaps only after hash-bound independent method review."""
import argparse
from pathlib import Path
import json
import production as p
import delivery as d
import boundary_chroma as b

DIRECTORY=p.HERE/'batch_02_corrections'
REQUIRED={'shot_001479','shot_001833','shot_002456','shot_009808'}


def verify_method_gate(path):
    gate=p.read_json(path)
    if gate.get('status')!='independent_method_visual_pass' or gate.get('delivery_acceptance') is not False:
        raise ValueError('Independent local method gate is missing; no correction launched')
    reviews=gate.get('reviews',[])
    if {row['shot_id'] for row in reviews}!=REQUIRED:
        raise ValueError('Both long moving and both short face transitions require independent review')
    registry=p.read_json(p.HERE/'source_y_overrides.json')
    for row in reviews:
        if p.sha256(row['review_path'])!=row['review_sha256']:raise ValueError('Independent review changed')
        review=p.read_json(row['review_path'])
        if review.get('status') not in {'local_corrected_neighborhood_review_pass','local_per_frame_neighborhood_review_pass'}:
            raise ValueError('Independent review does not pass the corrected neighborhood')
        override=registry[row['shot_id']]
        if override['status'] not in {'active_pending_quality_review','accepted'}:raise ValueError('A method trial is held for changes')
        treatment=p.read_json(override['receipt'])
        if review['output_sha256']!=override['output_sha256'] or review['output_sha256']!=row['output_sha256']:
            raise ValueError('Review is not bound to current treatment')
        if 'two-sided per-frame neural UV blend v2' not in treatment['method']:
            raise ValueError('Review must concern moving per-frame fields, not held endpoints')
        if not all(treatment.get(key) for key in ['full_decode_verified','exact_source_y','exact_outside_support_uv']):
            raise ValueError('Reviewed treatment lacks complete preservation proof')
    return gate


def main(gate_path):
    gate=verify_method_gate(gate_path)
    plan_path=DIRECTORY/'plan.json';plan=p.read_json(plan_path)
    canonical=p.validate_manifest(p.read_json(p.PROJECT/'scenes/second_batch_manifest.json'))
    identity=p.source_identity(canonical['source']);runtime=p.runtime_identity()
    measurement_path=Path(plan['source_measurement']);measurement=p.read_json(measurement_path)
    if p.sha256(measurement_path)!=plan['source_measurement_sha256'] or identity['sha256']!=plan['source_sha256']:
        raise ValueError('Mapped source or measurements changed')
    # This transition activates only the exact already-mapped correction jobs.
    for job in plan['jobs']:
        mapped=p.read_json(job['manifest']);selected=next(row for row in mapped['shots'] if row['id']==job['id'])
        approval=p.read_json(job['outgoing_approved_guide_marker'])
        frozen=p.read_json(Path(job['manifest']).parent/'approved_guides_source.snapshot.json')
        if approval['references']!=frozen['references']:raise ValueError('Mapped approved guide set changed')
        approval.update(shot_id=job['id'],scope_extension_authorization='Existing root authorization following independently validated batch1 per-frame method.',
            inherited_approval_path=job['outgoing_approved_guide_marker'],method_validation_path=str(gate_path),method_validation_sha256=p.sha256(gate_path),
            inference_purpose='Outgoing-scene UV hypothesis on actual source dissolve frames; final blend still pending independent review.')
        p.atomic_json(p.resolve(selected['references_ready']),approval)
        mapped['status']='authorized_after_independent_per_frame_method_review'
        selected['description']='Authorized outgoing-scene inference overlap after independent method validation.'
        active_manifest=Path(job['manifest']).with_name('manifest.json')
        p.atomic_json(active_manifest,p.validate_manifest(mapped));job['active_manifest']=str(active_manifest)
        job['readiness_published']=True
        job['status']='authorized_after_independent_method_review'
    plan.update(status='authorized_correction_queue',method_validation_path=str(gate_path),method_validation_sha256=p.sha256(gate_path))
    plan['launch_gate']['currently_satisfied']=True;p.atomic_json(plan_path,plan)
    p.STATUS_PATH=p.HERE/'batch_02_correction_queue_status.json'
    rendered=[]
    for job in plan['jobs']:
        document=p.validate_manifest(p.read_json(job['active_manifest']))
        shot=next(row for row in document['shots'] if row['id']==job['id'])
        args=argparse.Namespace(wait=True,wait_for_queue=True,rerender=False,max_shots=None,reason='authorized_batch02_per_frame_dissolve_correction')
        p.run_queue(args,document,{job['id']})
        if p.STOP.exists():return
        attempt=d.choose_attempt(shot,identity,runtime)
        if attempt is None:raise ValueError('Overlap did not produce a verified attempt')
        rendered.append((job,document,shot,attempt))
    plan.update(status='overlap_inference_complete',inference_finished_at=p.utc());p.atomic_json(plan_path,plan)
    with p.ExclusiveLock(p.HERE/'boundary_chroma.lock',wait=True):
        for job,document,selected,attempt in rendered:
            callback=lambda **details:b.update(stage='preparing_batch02_per_frame_overlap',shot_id=selected['id'],**details)
            overlap=d.merge_one(document,selected,attempt,identity,callback)
            target=next(row for row in canonical['shots'] if row['id']==job['incoming_shot_id'])
            outgoing=next(row for row in canonical['shots'] if row['id']==job['outgoing_shot_id'])
            bases=[]
            for shot in [target,outgoing]:
                current=d.choose_attempt(shot,identity,runtime)
                if current is None:raise ValueError('Adjacent baseline unavailable')
                bases.append(d.merge_one(canonical,shot,current,identity,callback))
            transition=next(row for row in measurement['transitions'] if row['boundary_frame']==target['start_frame'])
            record,marker=b.repair(canonical,target,outgoing,bases[0],bases[1],transition,measurement,measurement_path,overlap=overlap)
            registry_path=p.HERE/'source_y_overrides.json';registry=p.read_json(registry_path)
            previous=registry.get(target['id'],{})
            if previous.get('status')=='changes_required' and previous.get('output_sha256')==record['output_sha256']:
                raise ValueError('Identical treatment was rejected; preserve QA hold')
            registry[target['id']]=dict(receipt=str(marker),output_sha256=record['output_sha256'],base_output_sha256=record['base_output_sha256'],
                status='active_pending_quality_review',support_start_frame=transition['support_start_frame'],support_end_frame_exclusive=transition['support_end_frame_exclusive'])
            p.atomic_json(registry_path,registry)
            print(json.dumps(dict(stage='batch02_per_frame_draft_ready',shot_id=target['id'],receipt=str(marker))),flush=True)
    plan.update(status='draft_per_frame_treatments_ready',quality_acceptance='pending',finished_at=p.utc());p.atomic_json(plan_path,plan)
    d.watch(argparse.Namespace(manifest=p.PROJECT/'scenes/second_batch_manifest.json',batch='batch_02',wait=True,wait_for_queue=True,status_path=None))


if __name__=='__main__':
    from recipe_guard import require_lecture1_recipe
    require_lecture1_recipe()
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--gate',type=Path,required=True)
    main(parser.parse_args().gate)
