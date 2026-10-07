"""CPU-only fully-neutral outgoing photo field, then measured source-alpha blend."""
import copy
import hashlib
from pathlib import Path
import json
import os
import numpy as np
import production as p
import delivery as d
import scientific_mask as sm
import boundary_chroma as b

PLAN=p.HERE/'scientific_dissolves/plan.json'
STATUS=p.HERE/'scientific_neutral_exit_status.json'

def update(**details):p.atomic_json(STATUS,dict(updated_at=p.utc(),pid=os.getpid(),quality_acceptance='pending',**details))

def source_uv_handle(document,scene,transition,attempt,identity,callback=None):
    start=transition['support_start_frame'];end=transition['support_end_frame_exclusive'];frames=end-start
    hypothesis=copy.deepcopy(scene);hypothesis.update(end_frame=end,end_frame_exclusive=end,frames=end-scene['start_frame'])
    passthrough=scene.get('mode')=='passthrough'
    if passthrough:
        canonical=next((s for s in document.get('shots',[]) if s['id']==scene['id']),None)
        if canonical!=scene:raise ValueError('Source UV passthrough must be a frozen canonical scene')
        config=None
    else:config=sm.load(hypothesis,document['source'],identity)
    if config is None and not passthrough:raise ValueError('A validated full-photo outgoing scene mask is required')
    pixels=document['source']['width']*document['source']['height']
    key=p.json_digest(dict(source=identity['sha256'],start=start,end=end,mask=config['content_digest'] if config else 'canonical_source_passthrough',method='original per-frame source YUV v1'))
    folder=p.RENDER/'delivery/scientific_source_uv'/scene['id']/('handle_'+key[:16]);folder.mkdir(parents=True,exist_ok=True)
    marker=folder/'source_uv.json';output=folder/'source_yuv444_ffv1.mkv'
    if marker.exists():
        old=p.read_json(marker)
        if old.get('status')=='draft_verified' and old.get('fingerprint')==key and output.is_file() and p.sha256(output)==old['output_sha256']:return old
    if config:
      with (folder/'mask.log').open('w') as log:
        reader=d.decoder(config['path'],'gray',log,start-config['record']['start_frame'],frames)
        try:
            for _ in range(frames):
                data=d.read_exact(reader.stdout,pixels)
                if len(data)!=pixels or not np.all(np.frombuffer(data,np.uint8)==255):raise ValueError('Outgoing scene includes unmasked pixels: analytic full-photo field refused')
            if reader.stdout.read(1):raise ValueError('Excess mask support frames')
        finally:reader.stdout.close();code=reader.wait()
        if code:raise ValueError('Mask decode failed')
    clip=attempt['source_clip'];local=start-clip['source_clip_start_frame']
    if clip['source_sha256']!=identity['sha256'] or not 0<=local or end>clip['source_clip_end_frame']:raise ValueError('Source handle cache does not cover original frames')
    if p.sha256(clip['path'])!=clip['sha256']:raise ValueError('Native source cache hash changed')
    command=[str(p.FFMPEG),'-v','error','-xerror','-y','-threads','2','-filter_threads','2','-i',clip['path'],
        '-map','0:v:0','-vf',f'trim=start_frame={local}:end_frame={local+frames},setpts=PTS-STARTPTS',
        '-frames:v',str(frames),'-fps_mode','passthrough','-an','-sn','-c:v','ffv1','-level','3','-threads','2','-pix_fmt','yuv444p',str(output)]
    (callback or update)(stage='preparing_original_photo_uv',start_frame=start,end_frame=end)
    d.run_logged(command,folder/'extract.log')
    y=hashlib.sha256();all_planes=hashlib.sha256()
    with (folder/'verify_source.log').open('w') as sl,(folder/'verify_output.log').open('w') as ol:
        readers=[d.decoder(clip['path'],'yuv444p',sl,local,frames),d.decoder(output,'yuv444p',ol)]
        try:
            for _ in range(frames):
                before,after=[d.read_exact(child.stdout,pixels*3) for child in readers]
                if len(before)!=pixels*3 or before!=after:raise ValueError('Original photo field must preserve every native Y/U/V sample')
                y.update(after[:pixels]);all_planes.update(after)
            if any(child.stdout.read(1) for child in readers):raise ValueError('Excess photo field frames')
        finally:
            for child in readers:child.stdout.close()
            codes=[child.wait() for child in readers]
        if any(codes):raise ValueError('Photo field proof decode failed')
    d.verify_video_geometry(output,document['source'])
    record=dict(schema_version=1,status='draft_verified',shot_id=f'neutral_uv_{start:06d}_{end:06d}',
        field_origin='original_source_uv_canonical_passthrough' if passthrough else 'original_source_uv_fully_neutral_photo',source_sha256=identity['sha256'],fingerprint=key,
        start_frame=start,end_frame=end,frames=frames,output=str(output),output_sha256=p.sha256(output),
        exact_source_y=True,exact_original_source_uv=True,whole_photo_mask_verified=not passthrough,canonical_passthrough_verified=passthrough,full_decode_verified=True,
        source_y=dict(sha256=y.hexdigest(),decoded_bytes=frames*pixels),source_yuv_sha256=all_planes.hexdigest(),
        source_clip_mapping=clip,mask_marker=str(config['marker']) if config else None,mask_sha256=config['record']['mask_sha256'] if config else None,
        mask_content_digest=config['content_digest'] if config else None,timing=d.verify_timestamps(output,frames,document['source']),
        method='Exact per-frame original UV because validated outgoing photo matte covers every pixel; no neural prediction or held field.',
        quality_acceptance='pending actual source-alpha composite review',finished_at=p.utc())
    p.atomic_json(marker,record);return record

def main():
    plan=p.read_json(PLAN);job=next(j for j in plan['jobs'] if j['boundary_frame']==51364)
    if p.sha256(plan['canonical_manifest'])!=plan['canonical_manifest_sha256'] or p.sha256(plan['measurement_path'])!=plan['measurement_sha256']:raise ValueError('Frozen science mapping changed')
    document=p.validate_manifest(p.read_json(plan['canonical_manifest']));measurement=p.read_json(plan['measurement_path'])
    identity=p.source_identity(document['source']);runtime=p.runtime_identity()
    target=next(s for s in document['shots'] if s['id']==job['incoming_shot_id'])
    outgoing=next(s for s in document['shots'] if s['id']==job['outgoing_shot_id'])
    callback=lambda **details:update(stage='compositing_original_photo_exit',**details)
    with p.ExclusiveLock(p.HERE/'boundary_chroma.lock',wait=True),p.ExclusiveLock(p.HERE/'delivery_queue.lock',wait=True):
        bases=[];attempts=[]
        for side in [target,outgoing]:
            attempt=d.choose_attempt(side,identity,runtime)
            if attempt is None:raise ValueError('Scientific scene inference is not ready')
            attempts.append(attempt);bases.append(d.merge_one(document,side,attempt,identity,callback))
        overlap=source_uv_handle(document,outgoing,job['transition'],attempts[1],identity)
        record,marker=b.repair(document,target,outgoing,bases[0],bases[1],job['transition'],measurement,Path(plan['measurement_path']),overlap=overlap)
        registry_path=p.HERE/'source_y_overrides.json';registry=p.read_json(registry_path)
        registry[target['id']]=dict(receipt=str(marker),output_sha256=record['output_sha256'],base_output_sha256=record['base_output_sha256'],
            status='active_pending_quality_review',support_start_frame=job['support_half_open'][0],support_end_frame_exclusive=job['support_half_open'][1])
        p.atomic_json(registry_path,registry)
        # Read again before this one-job update so another science job cannot be
        # clobbered by this CPU branch's earlier plan snapshot.
        plan=p.read_json(PLAN);job=next(j for j in plan['jobs'] if j['boundary_frame']==51364)
        job.update(status='draft_treatment_ready_pending_native_QA',receipt=str(marker),output_sha256=record['output_sha256'],
            worker_launched=True,gpu_used=False,finished_at=p.utc());p.atomic_json(PLAN,plan)
        update(stage='draft_original_photo_exit_ready_pending_QA',receipt=str(marker),output_sha256=record['output_sha256'],gpu_used=False)
        print(json.dumps(dict(receipt=str(marker),output=record['output'],output_sha256=record['output_sha256'],gpu_used=False)))

if __name__=='__main__':
    try:main()
    except BaseException as error:update(stage='failed',error=str(error));raise
