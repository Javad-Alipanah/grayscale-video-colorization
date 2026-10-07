"""Follow the completed batch-3 queue with approved per-frame repairs and drafts."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import production as p
import delivery as d
import boundary_chroma as b
from run_reviewed_batch02_corrections import verify_method_gate

PLAN=p.HERE/'ordered_remaining_repairs/plan.json'
STATUS=p.HERE/'ordered_remaining_repairs_status.json'

def status(stage,**values):
    p.atomic_json(STATUS,dict(stage=stage,pid=os.getpid(),updated_at=p.utc(),quality_acceptance='pending',**values))

def dependency_complete(state,expected):
    return state.get('stage')=='queue_complete' and state.get('selected_expected_frames')==expected and state.get('selected_rendered_frames')==expected

def pending_before_gpu_dependencies(plan):
    return [str(path) for path in plan.get('before_gpu_dependencies',[])
        if not Path(path).exists() or p.read_json(path).get('status')!='bounded_mask_trial_complete_pending_QA']

def completed_job_valid(job,shot,identity,runtime):
    if job.get('status')!='draft_treatment_ready' or not job.get('receipt'):return False
    saved=p.read_json(job['receipt']);registry=p.read_json(p.HERE/'source_y_overrides.json').get(job['incoming_shot_id'],{})
    if saved.get('status')!='draft_verified' or saved.get('output_sha256')!=job.get('output_sha256') or registry.get('output_sha256')!=job['output_sha256']:return False
    if registry.get('status') not in {'active_pending_quality_review','accepted'}:return False
    if not all(saved.get(k) is True for k in ['exact_source_y','full_decode_verified','exact_outside_support_uv']):return False
    attempt=d.choose_attempt(shot,identity,runtime)
    if attempt is None or saved.get('overlap_master',{}).get('prediction_sha256')!=attempt['output_sha256']:return False
    if not Path(saved['output']).is_file() or p.sha256(saved['output'])!=saved['output_sha256'] or p.sha256(attempt['output'])!=attempt['output_sha256']:return False
    p.reject_failed_chroma_review(job['incoming_shot_id'],saved['output_sha256'])
    return True

def main():
    plan=p.read_json(PLAN)
    if not plan.get('launch_authorized'):raise ValueError('Plan is not authorized')
    gate=Path(plan['method_validation_path'])
    if p.sha256(gate)!=plan['method_validation_sha256']:raise ValueError('Method review gate changed')
    verify_method_gate(gate)
    while not dependency_complete(p.read_json(plan['dependency_status']),plan['dependency_expected_frames']):
        if p.STOP.exists():status('stopped_at_dependency');return
        status('waiting_for_primary_dependency',note='Require the entire selected batch, not a between-shot GPU lock release.')
        time.sleep(5)
    while pending_before_gpu_dependencies(plan):
        if p.STOP.exists():status('stopped_at_mask_dependency');return
        status('waiting_for_bounded_mask_dependencies',pending=pending_before_gpu_dependencies(plan))
        time.sleep(5)
    while True:
        if p.STOP.exists():status('stopped_at_storage_boundary');return
        if plan.get('refresh_forecast_script'):
            subprocess.run([str(p.PYTHON),plan['refresh_forecast_script']],check=True,stdout=subprocess.DEVNULL)
            required=p.read_json(plan['storage_forecast'])['required_free_at_gpu_start_gib']
        else:required=plan['disk_budget']['required_free_gib']
        free=shutil.disk_usage(p.WORKSPACE).free/2**30
        if free>=required:break
        status('held_for_disk_budget',free_gib=free,required_gib=required)
        if not plan.get('wait_for_storage'):return
        time.sleep(30)
    canonical=p.validate_manifest(p.read_json(plan['jobs'][0]['canonical_manifest']))
    identity=p.source_identity(canonical['source']);runtime=p.runtime_identity()
    p.STATUS_PATH=Path(plan.get('gpu_status_path',p.HERE/'ordered_remaining_repairs_gpu_status.json'))
    plan.update(status='running',started_at=plan.get('started_at') or p.utc());p.atomic_json(PLAN,plan)
    for job in plan['jobs']:
        if p.STOP.exists():status('stopped_at_job_boundary');return
        for path_key,sha_key in [('manifest','manifest_sha256'),('measurement_path','measurement_sha256'),('canonical_manifest','canonical_manifest_sha256')]:
            if p.sha256(job[path_key])!=job[sha_key]:raise ValueError(f'Frozen repair input changed: {path_key}')
        document=p.validate_manifest(p.read_json(job['manifest']));shot=next(s for s in document['shots'] if s['id']==job['id'])
        if completed_job_valid(job,shot,identity,runtime):
            status('resumed_verified_treatment',job_id=job['id'],receipt=job['receipt']);continue
        if job['source_bridge_cache_required']:
            status('preparing_native_bridge',job_id=job['id'])
            clip=p.prepare_batch(document,job['bridge_batch_id'],identity)
            proof=Path(job['manifest']).parent/'bridge_original_y_verification.json'
            if not proof.exists() or p.read_json(proof).get('cache_sha256')!=clip['sha256']:
                before=d.video_y_hash(identity['path'],proof.with_suffix('.source.log'),job['inference_range_half_open'][0],job['inference_frames'])
                after=d.video_y_hash(clip['path'],proof.with_suffix('.cache.log'))
                if before!=after:raise ValueError('Native source bridge Y differs from original')
                p.atomic_json(proof,dict(status='verified',exact_original_y=True,source_sha256=identity['sha256'],cache_sha256=clip['sha256'],frames=job['inference_frames'],y=before))
        job.update(status='rendering',worker_launched=True);p.atomic_json(PLAN,plan)
        status('rendering',job_id=job['id'],verified_context_frames=sum(j['inference_frames'] for j in plan['jobs'] if j.get('status')=='draft_treatment_ready'))
        p.run_queue(argparse.Namespace(wait=True,wait_for_queue=True,rerender=False,max_shots=None,reason='authorized_ordered_remaining_dissolve_repairs'),document,{shot['id']})
        if p.STOP.exists():status('stopped_at_gpu_boundary');return
        attempt=d.choose_attempt(shot,identity,runtime)
        if attempt is None:raise ValueError('Completed context has no verified inference')
        target=next(s for s in canonical['shots'] if s['id']==job['incoming_shot_id']);outgoing=next(s for s in canonical['shots'] if s['id']==job['outgoing_shot_id'])
        callback=lambda **details:status('compositing',job_id=job['id'],**details)
        with p.ExclusiveLock(p.HERE/'boundary_chroma.lock',wait=True),p.ExclusiveLock(p.HERE/'delivery_queue.lock',wait=True):
            overlap=d.merge_one(document,shot,attempt,identity,callback)
            bases=[]
            for side in [target,outgoing]:
                current=d.choose_attempt(side,identity,runtime)
                if current is None:raise ValueError('Canonical adjacent baseline is unavailable')
                bases.append(d.merge_one(canonical,side,current,identity,callback))
            measurement=p.read_json(job['measurement_path'])
            record,marker=b.repair(canonical,target,outgoing,bases[0],bases[1],job['transition'],measurement,Path(job['measurement_path']),overlap=overlap)
            registry_path=p.HERE/'source_y_overrides.json';registry=p.read_json(registry_path)
            p.reject_failed_chroma_review(target['id'],record['output_sha256'])
            registry[target['id']]=dict(receipt=str(marker),output_sha256=record['output_sha256'],base_output_sha256=record['base_output_sha256'],
                status='active_pending_quality_review',support_start_frame=job['delivery_patch_range_half_open'][0],support_end_frame_exclusive=job['delivery_patch_range_half_open'][1])
            p.atomic_json(registry_path,registry)
        job.update(status='draft_treatment_ready',receipt=str(marker),output_sha256=record['output_sha256'],finished_at=p.utc());p.atomic_json(PLAN,plan)
        status('draft_treatment_ready',job_id=job['id'],shot_id=target['id'],receipt=str(marker))
        print(json.dumps(dict(stage='draft_treatment_ready',shot_id=target['id'],receipt=str(marker))),flush=True)
    plan.update(status='draft_per_frame_treatments_ready',inference_finished_at=p.utc());p.atomic_json(PLAN,plan)
    for batch,manifest,filename in plan.get('assemblies',[('batch_01',p.PROJECT/'scenes/first_batch_manifest.json','batch_01_remaining_repairs_delivery_status.json'),
        ('batch_03',p.HERE/'batch_03_manifest.json','batch_03_refined_delivery_status.json')]):
        if p.STOP.exists():status('stopped_at_assembly_boundary');return
        status('assembling_revised_draft',batch_id=batch)
        d.watch(argparse.Namespace(manifest=Path(manifest),batch=batch,wait=True,wait_for_queue=True,status_path=p.HERE/filename))
    plan.update(status='revised_drafts_ready_pending_review',finished_at=p.utc(),delivery_acceptance=False);p.atomic_json(PLAN,plan)
    status('revised_drafts_ready_pending_review',plan=str(PLAN))

if __name__=='__main__':
    from recipe_guard import require_lecture1_recipe
    require_lecture1_recipe()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,default=PLAN);parser.add_argument('--status',type=Path,default=STATUS)
    args=parser.parse_args();PLAN=args.plan;STATUS=args.status
    try:main()
    except BaseException as error:
        status('failed',error=str(error));raise
