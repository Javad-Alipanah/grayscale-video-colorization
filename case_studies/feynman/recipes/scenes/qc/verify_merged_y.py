"""Independent full decoded-Y digests: original source partitions vs merged FFV1."""
from pathlib import Path
import argparse,datetime,hashlib,json,subprocess
from sample_native import ROOT,BASE,FF,W,H

def reader(path,frames=None,start=0):
    vf='extractplanes=y' if frames is None else f'trim=start_frame={start}:end_frame={frames},extractplanes=y'
    return subprocess.Popen([str(FF),'-v','error','-xerror','-threads','2','-filter_threads','2',
        '-i',str(path),'-an','-sn','-vf',vf,'-fps_mode','passthrough','-threads','2',
        '-pix_fmt','gray','-f','rawvideo','-'],stdout=subprocess.PIPE)

def take_digest(stream,size,aggregate=None):
    remaining=size;digest=hashlib.sha256()
    while remaining:
        part=stream.read(min(remaining,4*1024*1024))
        if not part:raise ValueError(f'Short stream, missing{remaining} bytes')
        digest.update(part);remaining-=len(part)
        if aggregate is not None:aggregate.update(part)
    return digest.hexdigest()

def originals(batch='batch_01'):
    manifest_path=BASE.parent/('first_batch_manifest.json' if batch=='batch_01' else 'manifest.json')
    if batch=='batch_04':
        manifest_path=ROOT/'work/lecture1-color/engine/batch_04_manifest.json'
    manifest=json.loads(manifest_path.read_text())
    source=json.loads((BASE.parent/'manifest.json').read_text())['source']
    parts=[{'shot_id':s['id'],'start_frame':s['start_frame'],'end_frame':s['end_frame']} for s in manifest['shots'] if batch=='batch_01' or s['batch_id']==batch]
    fingerprint=hashlib.sha256(json.dumps(parts,sort_keys=True).encode()).hexdigest()
    target=BASE/f'source_{batch}_per_shot_y.json'
    if target.exists():
        old=json.loads(target.read_text())
        if old['source_sha256']==source['sha256'] and old['partition_sha256']==fingerprint:return old
    process=reader(source['path'],parts[-1]['end_frame'],parts[0]['start_frame'])
    records={};aggregate=hashlib.sha256()
    for part in parts:
        count=part['end_frame']-part['start_frame'];size=count*W*H
        records[part['shot_id']]={**part,'frames':count,'decoded_Y_bytes':size,'Y_sha256':take_digest(process.stdout,size,aggregate)}
        print(json.dumps({'original_Y_partition_hashed':part['shot_id'],'frames':count}),flush=True)
    if process.stdout.read(1):raise ValueError('Extra original source frames')
    process.stdout.close()
    if process.wait()!=0:raise ValueError('Original source decoder failure')
    result={'schema_version':1,'batch_id':batch,'source':source['path'],'source_sha256':source['sha256'],
            'full_batch_Y_sha256':aggregate.hexdigest(),'frames':parts[-1]['end_frame']-parts[0]['start_frame'],
            'partition_sha256':fingerprint,'shots':records,'method':'Single sequential native decoded original Y pass; half-open global frame partitions; no resampling or seek rounding.'}
    target.write_text(json.dumps(result,indent=2));return result

def verify(shots,batch='batch_01'):
    proof=originals(batch)
    registry_path=ROOT/'work/lecture1-color/engine'/('delivery_status.json' if batch=='batch_01' else f'{batch}_delivery_status.json')
    registry=json.loads(registry_path.read_text())['merge_registry']
    selected=shots or list(registry)
    for shot in selected:
        entry=registry[shot]
        if entry['status']!='draft_verified' or not entry['exact_source_y'] or not entry['full_decode_verified']:continue
        folder=BASE/'merged'/shot/entry['output_sha256'][:12];folder.mkdir(parents=True,exist_ok=True)
        target=folder/'independent_full_Y_verification.json'
        if target.exists():
            previous=json.loads(target.read_text())
            if previous['output_sha256']==entry['output_sha256'] and previous['status']=='pass':continue
        expected=proof['shots'][shot]
        process=reader(entry['output'])
        digest=hashlib.sha256();size=0
        while True:
            part=process.stdout.read(4*1024*1024)
            if not part:break
            digest.update(part);size+=len(part)
        process.stdout.close()
        if process.wait()!=0:raise ValueError('Merged decoder failure')
        actual=digest.hexdigest();passed=size==expected['decoded_Y_bytes'] and actual==expected['Y_sha256']
        result={'schema_version':1,'shot_id':shot,'status':'pass' if passed else 'fail',
            'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'output':entry['output'],
            'output_sha256':entry['output_sha256'],'start_frame':expected['start_frame'],'end_frame':expected['end_frame'],
            'expected_frames':expected['frames'],'decoded_Y_bytes':size,'decoded_frames':size/(W*H),
            'source_Y_sha256':expected['Y_sha256'],'merged_Y_sha256':actual,'exact_original_Y_all_frames':passed,
            'source_sha256':proof['source_sha256'],'source_digest_receipt':str((BASE/f'source_{batch}_per_shot_y.json').resolve()),
            'delivery_acceptance':False,'scope':'Independent full original-versus-merged decoded Y verification; does not establish chroma quality, audio, or final batch acceptance.'}
        target.write_text(json.dumps(result,indent=2))
        print(json.dumps({'shot':shot,'status':result['status'],'all_frames':expected['frames']}),flush=True)
        if not passed:raise ValueError(f'Native Y mismatch in{shot}')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--shot',action='append');parser.add_argument('--batch',default='batch_01');args=parser.parse_args();verify(args.shot,args.batch)
