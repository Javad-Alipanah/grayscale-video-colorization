"""Independent batch original Y, decoded PCM and packet cadence verification."""
from pathlib import Path
from datetime import datetime,timezone
from fractions import Fraction
import argparse,hashlib,json,subprocess
import numpy as np
from sample_native import ROOT,BASE,FF,W,H
from verify_merged_y import reader
BATCH='batch_01';START=0;END=15017
COUNT=END-START;RATE=48000;CHANNELS=2;SAMPLES=COUNT*2002
NATURAL_SOURCE_EOF=False
PROBE=ROOT/'work/download-tools/ffprobe.exe'

def stream_hash(command):
    p=subprocess.Popen(command,stdout=subprocess.PIPE);h=hashlib.sha256();size=0
    for part in iter(lambda:p.stdout.read(4*1024*1024),b''):h.update(part);size+=len(part)
    p.stdout.close()
    if p.wait()!=0:raise ValueError('Decode failed')
    return {'bytes':size,'sha256':h.hexdigest()}

def pcm(path,trim=False):
    command=[str(FF),'-v','error','-xerror','-threads','2','-i',str(path),'-map','0:a:0','-vn','-sn']
    if trim:command+=['-af',f'atrim=start_sample={START*2002}'+('' if NATURAL_SOURCE_EOF else f':end_sample={END*2002}')]
    command+=['-c:a','pcm_f32le','-f','f32le','-']
    result=stream_hash(command)
    if result['bytes']%(CHANNELS*4):raise ValueError('Incomplete native PCM sample')
    if SAMPLES is not None and result['bytes']!=SAMPLES*CHANNELS*4:raise ValueError('Wrong native PCM sample count')
    return result

def source_pcm():
    global SAMPLES
    source=json.loads((BASE.parent/'manifest.json').read_text())['source'];path=BASE/f'source_{BATCH}_pcm.json'
    if path.exists():
        result=json.loads(path.read_text())
        if result['source_sha256']==source['sha256'] and result['samples_per_channel']==SAMPLES and result.get('start_frame',0)==START:return result
    decoded=pcm(source['path'],True)
    if NATURAL_SOURCE_EOF:SAMPLES=decoded['bytes']//(CHANNELS*4)
    result={'source_sha256':source['sha256'],'source':source['path'],'samples_per_channel':SAMPLES,
            'sample_rate':RATE,'channels':CHANNELS,'sample_format':'decoded float32 little endian',
            'batch_id':BATCH,'start_frame':START,'end_frame':END,
            'trim_policy':f'Exact sample range [{START*2002},'+('natural source EOF)' if NATURAL_SOURCE_EOF else f'{END*2002})')+'; no resampling, padding or enhancement',
            'pcm':decoded,'verified_at':datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(result,indent=2));return result

def verify(master):
    master=Path(master).resolve();folder=BASE/'batch_masters'/master.parent.name;folder.mkdir(parents=True,exist_ok=True)
    expected=json.loads((BASE/f'source_{BATCH}_per_shot_y.json').read_text())
    if 'full_batch_Y_sha256' not in expected:
        if BATCH!='batch_01':raise ValueError('Missing original full-batch Y proof')
        legacy=json.loads((BASE/'source_cache_full_digest.json').read_text());original=legacy['streams']['source_batch_Y']
        if legacy['status']!='pass' or original['frames']!=COUNT or Path(original['path']).resolve()!=Path(expected['source']).resolve():raise ValueError('Legacy original-Y proof mismatch')
        expected={**expected,'frames':original['frames'],'full_batch_Y_sha256':original['sha256']}
    p=reader(master);digest=hashlib.sha256();size=0
    for part in iter(lambda:p.stdout.read(4*1024*1024),b''):digest.update(part);size+=len(part)
    p.stdout.close()
    if p.wait()!=0:raise ValueError('Master video decode failed')
    if expected['frames']!=COUNT or size!=COUNT*W*H or digest.hexdigest()!=expected['full_batch_Y_sha256']:raise ValueError('Master original Y mismatch')
    print(json.dumps({'phase':'full_master_Y_pass','frames':COUNT}),flush=True)
    streams=json.loads(subprocess.check_output([str(PROBE),'-v','error','-show_streams','-of','json',str(master)]))['streams']
    video=next(s for s in streams if s['codec_type']=='video');audio=next(s for s in streams if s['codec_type']=='audio')
    if (video['width'],video['height'],video['codec_name'],Fraction(video['r_frame_rate']))!=(W,H,'ffv1',Fraction(24000,1001)):
        raise ValueError('Master video geometry/codec/cadence metadata mismatch')
    if (audio['codec_name'],int(audio['sample_rate']),audio['channels'])!=('pcm_f32le',RATE,CHANNELS):
        raise ValueError('Master PCM metadata mismatch')
    packets=json.loads(subprocess.check_output([str(PROBE),'-v','error','-select_streams','v:0','-show_packets','-show_entries','packet=pts,duration','-of','json',str(master)]))['packets']
    pts=np.array([int(p['pts']) for p in packets]);tb=float(Fraction(video['time_base']));seconds=pts*tb
    if len(pts)!=COUNT or not np.all(np.diff(pts)>0):raise ValueError('Master presentation count/order mismatch')
    error=float(np.max(np.abs(seconds-np.arange(COUNT)*1001/24000)))
    if error>.00051:raise ValueError('Master cadence error exceeds native millisecond rounding')
    sourcepts=np.array(json.loads((BASE.parent/'source_pts.json').read_text())['source_pts'][START:END])/1000
    sourcepts-=sourcepts[0]
    original_pts_error=float(np.max(np.abs(seconds-sourcepts)))
    if original_pts_error>.00101:raise ValueError('Original PTS intervals differ beyond source millisecond rounding')
    pcm_original=source_pcm();pcm_master=pcm(master)
    if pcm_master!=pcm_original['pcm']:raise ValueError('Master decoded PCM differs from original source')
    h=hashlib.sha256()
    with master.open('rb') as file:
        for part in iter(lambda:file.read(4*1024*1024),b''):h.update(part)
    result={'schema_version':1,'status':'independent_integrity_pass_visual_acceptance_pending',
            'verified_at':datetime.now(timezone.utc).isoformat(),'master':str(master),'master_sha256':h.hexdigest(),
            'batch_id':BATCH,'start_frame':START,'end_frame':END,
            'frames':COUNT,'exact_original_Y_all_frames':True,'Y_sha256':digest.hexdigest(),
            'native_width':W,'native_height':H,'fps':'24000/1001','video_codec':'ffv1',
            'strictly_increasing_pts':True,'maximum_cadence_error_seconds':error,
            'maximum_original_PTS_difference_seconds':original_pts_error,
            'original_PTS_comparison':'Source packet times relative to first batch source frame; up to 1 ms difference allowed for independently rounded source/master millisecond time bases.',
            'source_PCM_receipt':str(BASE/f'source_{BATCH}_pcm.json'),'master_PCM':pcm_master,'exact_original_decoded_PCM':True,
            'delivery_acceptance':False,'scope':'Independently decoded full original-Y digest, original PCM sample digest, geometry and every video packet PTS. Does not replace visual/auditory playback review.'}
    (folder/'independent_master_verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--master');p.add_argument('--prepare-source-audio',action='store_true');p.add_argument('--batch',default='batch_01');args=p.parse_args()
    BATCH=args.batch
    batch=next(b for b in json.loads((BASE.parent/'manifest.json').read_text())['batches'] if b['id']==BATCH)
    START,END=batch['start_frame'],batch['end_frame'];COUNT=END-START;SAMPLES=COUNT*2002
    source=json.loads((BASE.parent/'manifest.json').read_text())['source']
    NATURAL_SOURCE_EOF=END==source['frame_count']
    if NATURAL_SOURCE_EOF:SAMPLES=None
    if args.prepare_source_audio:print(json.dumps(source_pcm()),flush=True)
    if args.master:verify(args.master)
