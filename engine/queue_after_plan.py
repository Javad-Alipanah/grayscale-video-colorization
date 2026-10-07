"""Wait for all dependency inference contexts, then render approved batch shots."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import time
import production as p

def dependency_inference_ready(dependency):
    return dependency.get('status') in {'overlap_inference_complete','draft_per_frame_treatments_ready',
        'revised_drafts_ready_pending_review','source_y_candidate_ready_pending_dense_QA','bounded_mask_trial_complete_pending_QA'}

def main(args):
    p.STATUS_PATH=args.status_path
    document=p.validate_manifest(p.read_json(args.manifest))
    selected={s['id'] for s in document['shots'] if s['batch_id']==args.batch}
    if not selected:raise ValueError('Requested batch is empty')
    while True:
        if p.STOP.exists():
            p.publish(document,selected,'stopped',note='Dependency waiter honored global stop at boundary.');return
        dependency=p.read_json(args.dependency_plan)
        if dependency_inference_ready(dependency):break
        p.publish(document,selected,'waiting_for_dependency_inference',note=f'Wait for ALL contexts in {args.dependency_plan}; individual OSlock releases do not satisfy this dependency.')
        time.sleep(5)
    while True:
        if p.STOP.exists():p.publish(document,selected,'stopped',note='Storage waiter honored global stop.');return
        refresh=getattr(args,'refresh_forecast_script',None)
        if refresh:subprocess.run([str(p.PYTHON),str(refresh)],check=True,stdout=subprocess.DEVNULL)
        forecast=p.read_json(args.storage_forecast)
        free=shutil.disk_usage(p.WORKSPACE).free/2**30
        if free>=forecast['required_free_at_gpu_start_gib']:break
        p.publish(document,selected,'held_for_disk_budget',note=f'Free{free:.2f}GiB below conservative start threshold{forecast["required_free_at_gpu_start_gib"]:.2f}GiB; no source/accepted files deleted.')
        if not getattr(args,'wait_for_storage',False):raise RuntimeError('Batch launch held for disk budget; inspect scoped status')
        time.sleep(30)
    args.wait=True;args.wait_for_queue=True;args.rerender=False;args.max_shots=None;args.reason=f'authorized_full_lecture_{args.batch}_after_correction_contexts'
    p.run_queue(args,document,selected)

if __name__=='__main__':
    from recipe_guard import require_lecture1_recipe
    require_lecture1_recipe()
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['manifest','dependency-plan','storage-forecast','status-path']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--batch',required=True)
    parser.add_argument('--refresh-forecast-script',type=Path)
    parser.add_argument('--wait-for-storage',action='store_true')
    main(parser.parse_args())
