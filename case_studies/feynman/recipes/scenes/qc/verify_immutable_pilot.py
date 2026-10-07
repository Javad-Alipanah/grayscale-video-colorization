"""Independent native Y/U/V preservation of the immutable approved pilot range."""
from datetime import datetime,timezone
from pathlib import Path
import argparse,hashlib,json,subprocess
from sample_native import ROOT,BASE,FF,W,H

P=W*H
START,END=21579,25899
COUNT=END-START
PILOT=ROOT/'outputs/Colorization_Continuous_Pilot/Caltech_Continuous_Color_3min_Lossless.mkv'
EXPECTED_ASSET_SHA='8e9e0b50c57ef145252b0fc3a019714a83452c2952f8ed677dbde2ce372d31e9'
PROOF=BASE/'immutable_pilot_native_planes.json'
PROBE=ROOT/'work/download-tools/ffprobe.exe'

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as file:
        for part in iter(lambda:file.read(4*1024*1024),b''):h.update(part)
    return h.hexdigest()

def metadata(path):
    streams=json.loads(subprocess.check_output([str(PROBE),'-v','error','-select_streams','v:0',
        '-show_entries','stream=codec_name,pix_fmt,width,height,color_range,color_space,r_frame_rate',
        '-of','json',str(path)]))['streams']
    data=streams[0]
    if (data['width'],data['height'],data['pix_fmt'],data['r_frame_rate'])!=(W,H,'yuv444p','24000/1001'):
        raise ValueError('Expected native 960x720 yuv444p at 24000/1001')
    return data

def planes(path,start=None):
    command=[str(FF),'-v','error','-xerror','-threads','2','-filter_threads','2','-i',str(path),'-map','0:v:0']
    if start is not None:command+=['-vf',f'trim=start_frame={start}:end_frame={start+COUNT}']
    command+=['-an','-sn','-fps_mode','passthrough','-threads','2','-pix_fmt','yuv444p','-f','rawvideo','-']
    process=subprocess.Popen(command,stdout=subprocess.PIPE)
    all_planes=hashlib.sha256();digest=[hashlib.sha256() for _ in range(3)];per_frame=[]
    for n in range(COUNT):
        frame=bytearray()
        while len(frame)<P*3:
            part=process.stdout.read(P*3-len(frame))
            if not part:raise ValueError(f'Short native pilot stream at frame {n}')
            frame.extend(part)
        all_planes.update(frame);per_frame.append(hashlib.sha256(frame).hexdigest())
        for plane in range(3):digest[plane].update(memoryview(frame)[plane*P:(plane+1)*P])
    if process.stdout.read(1):raise ValueError('Extra frames in native pilot stream')
    process.stdout.close()
    if process.wait()!=0:raise ValueError('Pilot native decode failed')
    return {'frames':COUNT,'total_native_YUV_bytes':COUNT*P*3,'bytes_per_plane':COUNT*P,
            'native_YUV_sha256':all_planes.hexdigest(),'Y_sha256':digest[0].hexdigest(),
            'U_sha256':digest[1].hexdigest(),'V_sha256':digest[2].hexdigest(),
            'per_frame_native_YUV_sha256':per_frame,'decode_command':command}

def prepare():
    asset_sha=sha(PILOT)
    if asset_sha!=EXPECTED_ASSET_SHA:raise ValueError('Approved immutable asset file SHA changed')
    if PROOF.exists():
        old=json.loads(PROOF.read_text())
        if old['asset_sha256']==asset_sha and old['status']=='immutable_native_planes_prepared':return old
    native=metadata(PILOT);result=planes(PILOT)
    original=json.loads((BASE/'source_batch_02_per_shot_y.json').read_text())
    if result['Y_sha256']!=original['shots']['shot_021579']['Y_sha256']:raise ValueError('Pilot native Y differs from independent source receipt')
    result.update({'schema_version':1,'status':'immutable_native_planes_prepared','asset':str(PILOT),
        'asset_sha256':asset_sha,'metadata':native,'start_frame':START,'end_frame':END,
        'source_sha256':original['source_sha256'],'exact_original_Y_all_frames':True,
        'verified_at':datetime.now(timezone.utc).isoformat(),'delivery_acceptance':False})
    PROOF.write_text(json.dumps(result,indent=2))
    return result

def verify(master,source):
    master=Path(master).resolve();assembly=json.loads((master.parent/'assembly.json').read_text())
    # The range must occur within the assembled batch; get the actual global start
    # from the batch named in the calling manifest, rather than guessing timestamps.
    batches=json.loads((BASE.parent/'manifest.json').read_text())['batches']
    batch=next(b for b in batches if b['id']=='batch_02')
    if (assembly['start_frame'],assembly['end_frame'])!=(batch['start_frame'],batch['end_frame']):
        raise ValueError('Expected the exact batch-2 assembly range')
    if assembly['source_sha256']!=source['source_sha256']:raise ValueError('Assembly/source SHA mismatch')
    metadata(master);result=planes(master,START-batch['start_frame'])
    for field in ['frames','native_YUV_sha256','Y_sha256','U_sha256','V_sha256','per_frame_native_YUV_sha256']:
        if result[field]!=source[field]:raise ValueError(f'Immutable pilot mismatch in {field}')
    result.update({'schema_version':1,'status':'pass','master':str(master),'master_sha256':sha(master),
        'batch_id':batch['id'],'global_range':[START,END],
        'local_master_range':[START-batch['start_frame'],END-batch['start_frame']],
        'immutable_pilot_receipt':str(PROOF),'asset_sha256':source['asset_sha256'],
        'exact_all_native_YUV_frames':True,'verified_at':datetime.now(timezone.utc).isoformat(),
        'delivery_acceptance':False,'scope':'Every native Y, U and V byte plus frame hashes match the approved pilot; no overall visual acceptance.'})
    folder=BASE/'batch_masters'/master.parent.name;folder.mkdir(parents=True,exist_ok=True)
    (folder/'immutable_pilot_verification.json').write_text(json.dumps(result,indent=2))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--master');args=parser.parse_args()
    result=prepare()
    if args.master:result=verify(args.master,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ['per_frame_native_YUV_sha256','decode_command']}),flush=True)
