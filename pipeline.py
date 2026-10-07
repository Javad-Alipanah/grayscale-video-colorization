"""Manually initiated, reviewed whole-shot batches; no automatic acceptance.

Supported source contract: progressive 8-bit limited-range BT.601 yuv420p,
zero-start CFR (24, 25, 30 or 24000/1001), one decoded-zero-start 48-kHz audio
stream. Negative AAC priming metadata is allowed only with a complete decoded
sample-clock proof; no audio sample shifting is performed.
Init probes every displayed video timestamp and binds source/census hashes.
"""
from __future__ import annotations
import argparse
import copy
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'engine'))
from audio_clock import verify_audio_clock


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def validate_probe(probe):
    streams = probe['streams']
    video = [s for s in streams if s['codec_type'] == 'video']
    audio = [s for s in streams if s['codec_type'] == 'audio']
    if len(video) != 1 or len(audio) != 1:
        raise ValueError('Exactly one video and one audio stream are supported')
    v, a = video[0], audio[0]
    if v.get('pix_fmt') != 'yuv420p' or v.get('color_range') != 'tv':
        raise ValueError('Source must explicitly identify limited-range 8-bit yuv420p')
    if v.get('color_space') not in {'bt470bg', 'smpte170m'}:
        raise ValueError('Explicit BT.601 matrix required; other/unknown matrices unsupported')
    if v.get('color_transfer') in {'smpte2084','arib-std-b67'}:
        raise ValueError('HDR transfer functions are unsupported')
    if v.get('field_order') not in {'progressive', 'unknown'}:
        raise ValueError('Interlaced source unsupported')
    if Fraction(v.get('start_time','0')) != 0:
        raise ValueError('Nonzero or negative source start unsupported')
    audio_start=Fraction(a.get('start_time','0'))
    if audio_start != 0 and (audio_start > 0 or a.get('codec_name') != 'aac'):
        raise ValueError('Nonzero audio start unsupported except proven AAC priming')
    fps = Fraction(v['r_frame_rate'])
    if fps not in {Fraction(24), Fraction(25), Fraction(30), Fraction(24000,1001)} or Fraction(v['avg_frame_rate']) != fps:
        raise ValueError('Unsupported FPS or variable frame rate')
    if int(a.get('sample_rate', 0)) != 48000 or int(a.get('channels', 0)) not in {1, 2}:
        raise ValueError('Only 48-kHz mono/stereo audio is supported')
    if audio_start != 0 or 'audio_frames' in probe:
        verify_audio_clock(a,probe.get('audio_frames',[]))
    if any(type(v.get(k)) is not int or v[k] <= 0 or v[k] % 2 for k in ['width', 'height']):
        raise ValueError('Positive even native dimensions required')
    frames = probe.get('frames', [])
    if not frames: raise ValueError('Full timestamp census required')
    tick = Fraction(v['time_base'])
    tolerance = min(tick,Fraction(1,1000))
    for index, f in enumerate(frames):
        if f.get('interlaced_frame', 0): raise ValueError('Interlaced frame unsupported')
        if 'best_effort_timestamp' not in f: raise ValueError('Missing displayed frame timestamp')
        actual = int(f['best_effort_timestamp']) * tick
        if (index == 0 and actual != 0) or actual < 0 or abs(actual - Fraction(index, 1)/fps) > tolerance:
            raise ValueError(f'Nonzero start, VFR or discontinuous PTS at frame {index}')
        if index and int(f['best_effort_timestamp']) <= int(frames[index-1]['best_effort_timestamp']):
            raise ValueError('Non-monotonic PTS')
    return {'frame_count':len(frames),'width':v['width'],'height':v['height'],
            'fps_num':fps.numerator,'fps_den':fps.denominator,'pixel_format':'yuv420p',
            'color_range':'tv','color_space':v['color_space'],'audio_sample_rate':48000}


def group_shots(census, source, seconds=600):
    if not seconds > 0: raise ValueError('Positive batch duration required')
    if census.get('status') != 'reviewed' or not census.get('reviewed_by') or not census.get('reviewed_at'):
        raise ValueError('Explicit reviewed shot census with reviewer and time required')
    shots = copy.deepcopy(census['shots']); expected=0; seen=set(); batches=[]; current=[]
    fps=Fraction(source['fps_num'],source['fps_den'])
    for s in shots:
        if not re.fullmatch(r'[A-Za-z0-9_-]+',str(s.get('id',''))) or s['id'] in seen: raise ValueError('Invalid/duplicate shot id')
        start,end=s.get('start_frame'),s.get('end_frame')
        if type(start) is not int or type(end) is not int or start != expected or end<=start:
            raise ValueError('Shot ranges must be nonempty contiguous half-open intervals, starting at zero (no gap/overlap)')
        if s.get('mode') not in {'colorize','passthrough','reusable_approved_master'}: raise ValueError('Explicit supported shot mode required')
        if s['mode']=='reusable_approved_master' and (not s.get('reuse_ready') or not s.get('source_asset')):
            raise ValueError('Reuse requires explicit approved master and readiness proof')
        # A source shot is indivisible; choose the nearest whole-shot boundary.
        if current and abs(Fraction(current[-1]['end_frame']-current[0]['start_frame'],1)/fps-seconds) <= abs(Fraction(end-current[0]['start_frame'],1)/fps-seconds):
            batches.append(current);current=[]
        current.append(s);expected=end;seen.add(s['id'])
    if current:batches.append(current)
    if expected != source['frame_count']:raise ValueError('Shot census must cover every source frame exactly')
    for i, group in enumerate(batches,1):
        for s in group:s['batch_id']=f'batch_{i:03}'
    return shots,[{'id':g[0]['batch_id'],'start_frame':g[0]['start_frame'],'end_frame':g[-1]['end_frame'],
                  'shots':[s['id'] for s in g],'review':'pending','stage':'not_started'} for g in batches]


def init_project(source_path,census_path,project,seconds=600):
    project=Path(project).resolve();target=project/'pipeline.json'
    if project.exists() and any(project.iterdir()):raise ValueError('Project must be a new or empty directory; existing files are never overwritten')
    source_path=Path(source_path).resolve();census_path=Path(census_path).resolve()
    ffprobe=os.environ.get('COLOR_FFPROBE','ffprobe')
    before=digest(source_path)
    probe=json.loads(subprocess.check_output([ffprobe,'-v','error','-show_streams','-show_frames',
        '-select_streams','v:0','-show_entries','stream:frame=best_effort_timestamp,interlaced_frame','-of','json',str(source_path)]))
    # Read all stream metadata separately: select_streams above limits frame census.
    probe['streams']=json.loads(subprocess.check_output([ffprobe,'-v','error','-show_streams','-of','json',str(source_path)]))['streams']
    probe['audio_frames']=json.loads(subprocess.check_output([ffprobe,'-v','error','-select_streams','a:0','-show_frames',
        '-show_entries','frame=best_effort_timestamp,nb_samples','-of','json',str(source_path)]))['frames']
    source=validate_probe(probe);source.update(path=str(source_path),sha256=before)
    if digest(source_path)!=before:raise ValueError('Source changed during probe')
    census=read(census_path);shots,batches=group_shots(census,source,seconds)
    for shot in shots:shot.setdefault('references_ready',str(project/'references'/shot['id']/'refs_ready.json'))
    for folder in ['engine','scenes','references','render']:(project/folder).mkdir(parents=True,exist_ok=True)
    atomic(project/'source_probe.json',probe)
    atomic(project/'scenes/manifest.json',{'schema_version':1,'source':source,'shots':shots})
    state={'schema_version':1,'source_sha256':before,'census_path':str(census_path),'census_sha256':digest(census_path),
           'source_probe_sha256':digest(project/'source_probe.json'),'manifest_sha256':digest(project/'scenes/manifest.json'),
           'batch_seconds':seconds,'batches':batches}
    atomic(target,state);return state


def load_project(project, check_references=True):
    project=Path(project).resolve();state=read(project/'pipeline.json');manifest=read(project/'scenes/manifest.json')
    if digest(project/'scenes/manifest.json')!=state['manifest_sha256']:raise ValueError('Stale/changed manifest; initialize a new versioned project')
    if digest(manifest['source']['path'])!=state['source_sha256']:raise ValueError('Stale source checksum')
    if digest(state['census_path'])!=state['census_sha256']:raise ValueError('Stale shot census')
    if digest(project/'source_probe.json')!=state['source_probe_sha256']:raise ValueError('Stale source probe')
    workspace=Path(os.environ.get('COLOR_WORKSPACE',ROOT)).resolve()
    if check_references:
        for shot in manifest['shots']:reference_state(shot,workspace,manifest['source'])
    for batch in state['batches']:
        if batch.get('review')=='accepted':
            review=batch.get('quality_review',{})
            if review.get('status')!='accepted' or review.get('master_sha256')!=batch.get('master_sha256'):
                raise ValueError('Accepted batch lacks matching explicit review')
            if digest(batch['master'])!=batch['master_sha256'] or digest(batch['assembly_receipt'])!=batch['assembly_receipt_sha256']:
                raise ValueError('Stale accepted batch media/receipt')
    return state,manifest


def reference_state(shot,workspace,source=None):
    if shot['mode']=='passthrough':return 'ready'
    marker=Path(shot['reuse_ready'] if shot['mode']=='reusable_approved_master' else shot['references_ready'])
    if not marker.is_absolute():marker=workspace/marker
    if not marker.exists():return 'pending'
    data=read(marker)
    if data.get('status')!='approved':return data.get('status','pending')
    if data.get('shot_id')!=shot['id'] or not data.get('approved_by') or not data.get('approved_at'):raise ValueError('Invalid reference/reuse review scope')
    if shot['mode']=='reusable_approved_master':return 'ready'  # Full reuse proof validated by production.
    refs=data.get('references',[])
    if not refs:raise ValueError('Approved marker contains no references')
    for item in refs:
        path=Path(item['path']);path=path if path.is_absolute() else workspace/path
        if digest(path)!=item['sha256']:raise ValueError('Stale reference checksum')
        if type(item.get('source_frame')) is not int or not shot['start_frame']<=item['source_frame']<shot['end_frame']:raise ValueError('Reference outside shot')
    from reference_provenance import validate_marker
    validate_marker(shot,source or shot.get('_source'),data,workspace)
    return 'ready'


def next_batch(state):
    # Rejected and pending work remain the next batch until explicitly resolved.
    return next((b for b in state['batches'] if b['review']!='accepted'),None)


def batch_review(project,batch_id,review):
    state,manifest=load_project(project);batch=next(b for b in state['batches'] if b['id']==batch_id)
    if batch.get('review')=='accepted':raise ValueError('Accepted batch review is immutable; use a new versioned project for changes')
    if batch.get('stage')!='delivered_pending_review':raise ValueError('Only delivered verified drafts can be reviewed')
    if review.get('status') not in {'accepted','rejected','pending'} or not all(review.get(k) for k in ['reviewed_by','reviewed_at','notes']):raise ValueError('Explicit attributed review required')
    if review.get('master_sha256')!=batch['master_sha256'] or digest(batch['master'])!=batch['master_sha256']:raise ValueError('Review master checksum mismatch')
    if digest(batch['assembly_receipt'])!=batch['assembly_receipt_sha256']:raise ValueError('Stale assembly receipt')
    batch.update(review=review['status'],quality_review=review)
    atomic(Path(project)/'pipeline.json',state);return batch


def revise_batch(project,batch_id,reason):
    if not reason or not reason.strip():raise ValueError('Explicit revision reason required')
    state,manifest=load_project(project);batch=next((b for b in state['batches'] if b['id']==batch_id),None)
    if batch is None or next_batch(state)!=batch or batch['review']=='accepted':
        raise ValueError('Only the next unresolved batch may be revised; accepted earlier batches are immutable in this wrapper')
    history=copy.deepcopy(batch.get('revisions',[]));snapshot=copy.deepcopy(batch);snapshot.pop('revisions',None)
    history.append({'reason':reason,'prior_state':snapshot})
    batch={k:batch[k] for k in ['id','start_frame','end_frame','shots']}
    minimum={}
    for sid in batch['shots']:
        records=[read(path) for path in (Path(project)/'render'/sid).glob('attempt_*/attempt.json')]
        minimum[sid]=max((r.get('attempt',0) for r in records),default=0)+1
    batch.update(stage='revision_pending_render',review='pending',revisions=history,force_rerender=True,revision_reason=reason,minimum_attempt_versions=minimum)
    state['batches']=[batch if b['id']==batch_id else b for b in state['batches']]
    atomic(Path(project)/'pipeline.json',state);return batch


def fresh_revision_shots(project,batch):
    fresh=set()
    for sid,minimum in batch.get('minimum_attempt_versions',{}).items():
        for path in (Path(project)/'render'/sid).glob('attempt_*/attempt.json'):
            r=read(path)
            if r.get('attempt',0)>=minimum and r.get('status') in {'pending_quality_review','accepted'} and r.get('full_decode_verified'):
                if Path(r.get('output','')).is_file() and digest(r['output'])==r.get('output_sha256'):fresh.add(sid)
    return fresh


def execute(project,batch_id,action):
    state,manifest=load_project(project);batch=next((b for b in state['batches'] if b['id']==batch_id),None)
    if batch is None:raise ValueError('Unknown batch')
    if next_batch(state)!=batch:raise ValueError('Only the next unresolved batch may run; no future autoqueue')
    project=Path(project).resolve();workspace=Path(os.environ.get('COLOR_WORKSPACE',ROOT)).resolve()
    selected=[s for s in manifest['shots'] if s['batch_id']==batch_id]
    if any(reference_state(s,workspace,manifest['source'])!='ready' for s in selected):raise ValueError('Selected batch references/reuse review pending or rejected')
    if batch.get('review')=='rejected':raise ValueError('Rejected batch needs a new explicitly versioned correction; wrapper will not revive it')
    if batch['stage']=='delivered_pending_review':raise ValueError('Delivered batch awaits review; do not overwrite it')
    if action=='deliver' and batch.get('force_rerender'):raise ValueError('Revision must render new attempts before delivery')
    env=dict(os.environ,COLOR_PROJECT=str(project),COLOR_WORKSPACE=str(workspace))
    python=env.get('COLOR_PYTHON',sys.executable)
    script=ROOT/'engine'/('production.py' if action=='render' else 'delivery.py')
    cmd=[python,str(script)]+(['run'] if action=='render' else [])+['--manifest',str(project/'scenes/manifest.json'),'--batch',batch_id]
    if action=='deliver':cmd+=['--status-path',str(project/'engine'/f'{batch_id}_delivery_status.json')]
    if action=='render' and batch.get('force_rerender'):
        remaining=[sid for sid in batch['shots'] if sid not in fresh_revision_shots(project,batch)]
        if remaining:
            cmd+=['--rerender','--reason',batch['revision_reason']]
            for sid in remaining:cmd+=['--shot',sid]
        else:
            batch['force_rerender']=False
    subprocess.run(cmd,env=env,check=True)
    if action=='render':
        batch['stage']='render_invoked_pending_shot_review'
        # A run invocation can return while waiting for references/STOP. Clear
        # the revision gate only after the selected scope actually completes.
        if batch.get('minimum_attempt_versions') and fresh_revision_shots(project,batch)==set(batch['shots']):
            batch['force_rerender']=False
    else:
        delivery=read(project/'engine'/f'{batch_id}_delivery_status.json')
        if delivery.get('stage')!='draft_scope_ready':raise ValueError('Delivery incomplete; inspect production/shot reviews')
        receipt=delivery['assembly'];receipt_path=Path(receipt['master']).parent/'assembly.json'
        if receipt.get('status')!='draft_verified_pending_visual_review' or not all(receipt.get(k) for k in ['exact_source_y','exact_source_pcm','full_decode_verified']):raise ValueError('Delivery preservation proof incomplete')
        if digest(receipt['master'])!=receipt['master_sha256']:raise ValueError('Delivered master checksum mismatch')
        batch.update(stage='delivered_pending_review',review='pending',master=receipt['master'],master_sha256=receipt['master_sha256'],
                     assembly_receipt=str(receipt_path),assembly_receipt_sha256=digest(receipt_path))
    atomic(project/'pipeline.json',state);return batch


def assemble(project):
    state,manifest=load_project(project)
    if next_batch(state) is not None:raise ValueError('All batches require explicit acceptance before full assembly')
    if state.get('full_artifact'):raise ValueError('Full draft already exists; preserve it and use a new versioned project for changes')
    project=Path(project).resolve();env=dict(os.environ,COLOR_PROJECT=str(project))
    path=project/'engine/full_delivery_status.json'
    subprocess.run([env.get('COLOR_PYTHON',sys.executable),str(ROOT/'engine/delivery.py'),'--full','--scope','full',
        '--manifest',str(project/'scenes/manifest.json'),'--status-path',str(path)],env=env,check=True)
    progress=read(path)
    if progress.get('stage')!='draft_scope_ready':raise ValueError('Full assembly incomplete; inspect scoped status')
    result=progress['assembly']
    if result.get('status')!='draft_verified_pending_visual_review' or not all(result.get(k) for k in ['exact_source_y','exact_source_pcm','full_decode_verified']):
        raise ValueError('Full preservation checks incomplete')
    expected={row['shot_id']:row['output_sha256'] for b in state['batches'] for row in read(b['assembly_receipt'])['shots']}
    actual={row['shot_id']:row['output_sha256'] for row in result['shots']}
    if expected!=actual:raise ValueError('Full assembly selected media differs from explicitly accepted batch media')
    if digest(result['master'])!=result['master_sha256']:raise ValueError('Full master checksum mismatch')
    receipt=Path(result['master']).parent/'assembly.json'
    state['full_artifact']={'status':'pending_independent_final_verification_and_visual_review','master':result['master'],
        'master_sha256':result['master_sha256'],'preview':result['preview'],'preview_sha256':result['preview_sha256'],
        'assembly_receipt':str(receipt),'assembly_receipt_sha256':digest(receipt),'automatically_accepted':False}
    atomic(project/'pipeline.json',state);return state['full_artifact']


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    init=sub.add_parser('init');init.add_argument('--source',required=True,type=Path);init.add_argument('--shots',required=True,type=Path)
    init.add_argument('--project',required=True,type=Path);init.add_argument('--batch-seconds',type=float,default=600)
    for action in ['status','next','render','deliver','review','revise','assemble']:
        p=sub.add_parser(action);p.add_argument('--project',required=True,type=Path)
        if action in {'render','deliver','review','revise'}:p.add_argument('--batch',required=True)
        if action=='review':p.add_argument('--review-file',type=Path,required=True)
        if action=='revise':p.add_argument('--reason',required=True)
    args=parser.parse_args()
    if args.action=='init':result=init_project(args.source,args.shots,args.project,args.batch_seconds)
    elif args.action in {'status','next'}:
        state,manifest=load_project(args.project)
        result=state if args.action=='status' else next_batch(state)
    elif args.action=='review':result=batch_review(args.project,args.batch,read(args.review_file))
    elif args.action=='revise':result=revise_batch(args.project,args.batch,args.reason)
    elif args.action=='assemble':result=assemble(args.project)
    else:result=execute(args.project,args.batch,args.action)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
