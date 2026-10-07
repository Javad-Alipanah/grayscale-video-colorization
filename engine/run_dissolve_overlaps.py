"""Own one GPU at a time, then blend moving UV hypotheses and rebuild the draft."""
import argparse
from pathlib import Path
import production as p
import delivery as d
import boundary_chroma as b

PLAN=p.HERE/'dissolve_overlaps/plan.json'


def main():
    plan=p.read_json(PLAN)
    p.STATUS_PATH=p.HERE/'dissolve_overlap_queue_status.json'
    canonical=p.validate_manifest(p.read_json(p.PROJECT/'scenes/first_batch_manifest.json'))
    identity=p.source_identity(canonical['source']);runtime=p.runtime_identity()
    measurement_path=p.PROJECT/'scenes/qc/dissolves/source_dissolve_map.json'
    measurement=p.read_json(measurement_path)
    if measurement['source_sha256'] != identity['sha256']:
        raise ValueError('Dissolve measurement belongs to a different original source')
    rendered=[]
    # The live batch2 queue holds the OS lock. Each overlap waits for orderly exit.
    for job in plan['jobs']:
        document=p.validate_manifest(p.read_json(job['manifest']))
        selected=next(shot for shot in document['shots'] if shot['id']==job['id'])
        args=argparse.Namespace(wait=True,wait_for_queue=True,rerender=False,max_shots=None,reason='authorized_per_frame_dissolve_overlap')
        p.run_queue(args,document,{job['id']})
        if p.STOP.exists(): return
        attempt=d.choose_attempt(selected,identity,runtime)
        if attempt is None: raise ValueError('Verified overlap inference missing')
        rendered.append((job,document,selected,attempt))
    plan.update(status='overlap_inference_complete',inference_finished_at=p.utc());p.atomic_json(PLAN,plan)
    with p.ExclusiveLock(p.HERE/'boundary_chroma.lock',wait=True):
        for job,document,selected,attempt in rendered:
            callback=lambda **details:b.update(stage='preparing_per_frame_overlap',shot_id=selected['id'],**details)
            overlap=d.merge_one(document,selected,attempt,identity,callback)
            target=next(shot for shot in canonical['shots'] if shot['id']==job['target_shot_id'])
            outgoing=next(shot for shot in canonical['shots'] if shot['end_frame']==target['start_frame'])
            bases=[]
            for shot in [target,outgoing]:
                current=d.choose_attempt(shot,identity,runtime)
                if current is None: raise ValueError('Current adjacent inference missing')
                bases.append(d.merge_one(canonical,shot,current,identity,callback))
            transition=next(row for row in measurement['transitions'] if row['boundary_frame']==job['boundary_frame'])
            record,marker=b.repair(canonical,target,outgoing,bases[0],bases[1],transition,measurement,measurement_path,overlap=overlap)
            registry_path=p.HERE/'source_y_overrides.json'
            registry=p.read_json(registry_path) if registry_path.exists() else {}
            previous=registry.get(target['id'],{})
            if previous.get('status')=='changes_required' and previous.get('output_sha256')==record['output_sha256']:
                raise ValueError('The identical per-frame treatment was already rejected; preserve the QA hold')
            registry[target['id']]=dict(receipt=str(marker),output_sha256=record['output_sha256'],
                base_output_sha256=record['base_output_sha256'],status='active_pending_quality_review',
                support_start_frame=transition['support_start_frame'],support_end_frame_exclusive=transition['support_end_frame_exclusive'])
            p.atomic_json(registry_path,registry)
    plan.update(status='draft_per_frame_treatments_ready',finished_at=p.utc(),quality_acceptance='pending');p.atomic_json(PLAN,plan)
    # Select hashes from the new registry; this creates a distinct assembly.
    d.watch(argparse.Namespace(manifest=p.PROJECT/'scenes/first_batch_manifest.json',batch='batch_01',wait=True,wait_for_queue=True,status_path=None))


if __name__=='__main__':
    from recipe_guard import require_lecture1_recipe
    require_lecture1_recipe()
    main()
