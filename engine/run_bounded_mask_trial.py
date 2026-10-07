"""One reviewed-anchor CUDA mask trial between audience repair and batch5."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import time
import production as p

PLAN=p.HERE/'bounded_mask_trial_plan.json'
STATUS=p.HERE/'bounded_mask_trial_status.json'

def validate_bidirectional_scope(plan, external):
    frames=plan['frames']
    expected_count=sum(j['end_frame']-j['start_frame']+1 for j in external['jobs'])
    limit=plan.get('authorized_frame_limit',389)
    exact_scopes={
        744:'b6159aadd70373488b72eb8394f31ab9d2460aa73bddd2f87b39dd6374c57832',
        1266:'0dc7e3fc8f63846dd7460342c39c57a002231f913f543298746e37a6c11d6372',
        1274:'05d27f9d66b85a828eb984139d692fa20580e7d699914fce24c9ada0e4b95e4f',
    }
    if limit not in {389,558,661,*exact_scopes} or frames!=expected_count or not 1<=frames<=limit:
        raise ValueError('Bidirectional trial exceeds its explicitly authorized frozen scope')
    if limit in exact_scopes and (frames!=limit or plan['source_trial_plan_sha256']!=exact_scopes[limit]):
        raise ValueError('Larger trial is not an explicitly reviewed frozen source scope')

def update(stage,**values):p.atomic_json(STATUS,dict(stage=stage,updated_at=p.utc(),pid=os.getpid(),production_delivery_acceptance=False,**values))

def dependency_ready(plan):
    if plan.get('dependency_queue_status'):
        path=Path(plan['dependency_queue_status'])
        if not path.exists():return False
        state=p.read_json(path);expected=plan['dependency_expected_frames']
        return (state.get('stage')=='queue_complete' and state.get('selected_rendered_frames')==expected
            and state.get('selected_expected_frames')==expected and state.get('active') is None)
    path=Path(plan['dependency_plan'])
    return path.exists() and p.read_json(path).get('status') in {'source_y_candidate_ready_pending_dense_QA','owned_gpu_handoff_complete','bounded_mask_trial_complete_pending_QA'}

def verified_completed_trial(plan):
    """Validate retained result bytes before bypassing the exclusive GPU job."""
    if plan.get('status')!='bounded_mask_trial_complete_pending_QA':return False
    receipt=Path(plan['result_receipt'])
    if p.sha256(receipt)!=plan['result_receipt_sha256']:raise ValueError('Completed source-mask receipt changed')
    result=p.read_json(receipt)
    if result.get('source_sha256')!=plan['source_sha256'] or result.get('frames')!=plan['frames']:
        raise ValueError('Completed source-mask scope changed')
    if plan.get('kind')=='bidirectional_source_foreground_trial':
        if p.sha256(plan['source_trial_plan'])!=plan['source_trial_plan_sha256']:raise ValueError('Completed source-mask plan changed')
        if result.get('status')!='bounded_mask_trial_integrity_pass_visual_QA_pending':raise ValueError('Completed source-mask integrity proof missing')
        results=[]
        for entry in result['receipts']:
            if p.sha256(entry['path'])!=entry['sha256']:raise ValueError('Completed direction receipt changed')
            direction=p.read_json(entry['path'])
            if direction.get('plan_sha256')!=plan['source_trial_plan_sha256'] or direction.get('script_sha256')!=plan['script_sha256']:
                raise ValueError('Completed mask direction provenance changed')
            results.append(direction)
        if sum(len(row['records']) for row in results)!=plan['frames']:raise ValueError('Completed mask frame coverage changed')
    else:results=[result]
    for record in results:
        for row in record['records']:
            if p.sha256(row['mask_path'])!=row['mask_sha256']:raise ValueError('Completed mask pixels changed; investigate instead of rerendering silently')
    return True

def main():
    plan=p.read_json(PLAN)
    if verified_completed_trial(plan):
        update('bounded_mask_trial_complete_pending_QA',result_receipt=plan['result_receipt'],frames=plan['frames'],resumed_without_gpu=True)
        return
    while not dependency_ready(plan):
        if p.STOP.exists():update('stopped_at_dependency');return
        update('waiting_for_declared_dependency');time.sleep(5)
    script=Path(plan['script'])
    if p.sha256(script)!=plan['script_sha256']:raise ValueError('Frozen mask trial script changed')
    if plan.get('cpu_review') and p.sha256(plan['cpu_review'])!=plan['cpu_review_sha256']:
        raise ValueError('Frozen source/CPU preflight review changed')
    update('waiting_for_exclusive_gpu_lock',frames=plan['frames'])
    with p.ExclusiveLock(p.GPU_LOCK,wait=True):
        if p.STOP.exists():update('stopped_at_gpu_boundary');return
        p.assert_gpu_idle()
        plan.update(status='trial_rendering',started_at=p.utc());p.atomic_json(PLAN,plan)
        frames=plan['frames'];start=plan.get('start_frame',46176)
        bidirectional=plan.get('kind')=='bidirectional_source_foreground_trial'
        if bidirectional:
            external_path=Path(plan['source_trial_plan'])
            if p.sha256(external_path)!=plan['source_trial_plan_sha256']:raise ValueError('Frozen bidirectional source-mask plan changed')
            external=p.read_json(external_path)
            validate_bidirectional_scope(plan,external)
            if external['source_sha256']!=plan['source_sha256']:raise ValueError('Bidirectional source identity changed')
            command=[str(p.PYTHON),str(script),'--plan',str(external_path),'--device','cuda','--engine-gpu-lock-held']
        else:
            if not 1<=frames<=176:raise ValueError('Bounded source-mask trial exceeds maximum authorized176frames')
            command=[str(p.PYTHON),str(script),'--device','cuda','--frames',str(frames),'--engine-gpu-lock-held']
        with (p.HERE/(PLAN.stem+'_child.stdout.log')).open('w') as out,(p.HERE/(PLAN.stem+'_child.stderr.log')).open('w') as err:
            child=subprocess.Popen(command,cwd=str(p.WORKSPACE),stdout=out,stderr=err)
            while child.poll() is None:
                update('trial_rendering',worker_pid=child.pid,frames=frames,command=command);time.sleep(2)
            if child.returncode:raise RuntimeError(f'Bounded mask trial failed with exit{child.returncode}; inspect child stderr')
        if p.sha256(script)!=plan['script_sha256']:raise ValueError('Mask trial script changed during execution')
        if bidirectional:
            if p.sha256(external_path)!=plan['source_trial_plan_sha256']:raise ValueError('Bidirectional source plan changed during execution')
            verified=[]
            for job in external['jobs']:
                for direction in ['forward','backward']:
                    order=list(range(job['anchor_frame'],job['end_frame'])) if direction=='forward' else list(range(job['anchor_frame'],job['start_frame']-1,-1))
                    rp=Path(job['output_root'])/('cuda_'+direction)/'trial.json';result=p.read_json(rp)
                    if result['device']!='cuda' or result['source_sha256']!=plan['source_sha256'] or result['frame_global_order']!=order or len(result['records'])!=len(order):raise ValueError('Bidirectional source mapping differs')
                    if result['script_sha256']!=plan['script_sha256'] or result['plan_sha256']!=plan['source_trial_plan_sha256']:raise ValueError('Trial provenance differs')
                    for frame,row in zip(order,result['records']):
                        if row['frame_global']!=frame or p.sha256(row['mask_path'])!=row['mask_sha256']:raise ValueError('Bidirectional trial frame hash differs')
                    verified.append(dict(path=str(rp),sha256=p.sha256(rp),frames=len(order),scene_id=job['scene_id'],direction=direction))
            receipt_path=p.HERE/(PLAN.stem+'_verification.json')
            p.atomic_json(receipt_path,dict(status='bounded_mask_trial_integrity_pass_visual_QA_pending',source_sha256=plan['source_sha256'],frames=frames,receipts=verified,delivery_acceptance=False))
            plan['result_receipt']=str(receipt_path)
        else:
            receipt_path=Path(plan['result_receipt']);result=p.read_json(receipt_path)
            if (result.get('device'),result.get('start_frame'),result.get('end_frame'),result.get('frames'))!=('cuda',start,start+frames,frames):raise ValueError('Mask trial range/device differs')
            if result.get('source_sha256')!=plan['source_sha256'] or len(result['records'])!=frames:raise ValueError('Mask trial source/count differs')
            for index,row in enumerate(result['records']):
                if row['frame_global']!=start+index or p.sha256(row['mask_path'])!=row['mask_sha256']:raise ValueError('Mask trial frame mapping/payload differs')
        plan.update(status='bounded_mask_trial_complete_pending_QA',finished_at=p.utc(),result_receipt_sha256=p.sha256(receipt_path),delivery_acceptance=False)
        p.atomic_json(PLAN,plan)
        update(plan['status'],result_receipt=str(receipt_path),frames=frames)
        print(json.dumps(dict(stage=plan['status'],result_receipt=str(receipt_path),frames=frames)),flush=True)

if __name__=='__main__':
    from recipe_guard import require_lecture1_recipe
    require_lecture1_recipe()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,default=PLAN);parser.add_argument('--status',type=Path,default=STATUS)
    args=parser.parse_args();PLAN=args.plan;STATUS=args.status
    try:main()
    except BaseException as error:update('failed',error=str(error));raise
