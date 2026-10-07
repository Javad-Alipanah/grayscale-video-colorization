"""Finite technical QA for the lecture upload derivative; no visual acceptance."""
import argparse, hashlib, json, math, os, subprocess
from pathlib import Path
from fractions import Fraction
from datetime import datetime, timezone

FF=os.environ.get('COLOR_FFMPEG', 'ffmpeg')
FP=os.environ.get('COLOR_FFPROBE', 'ffprobe')
MASTER_SHA='3acf35ef295edb52469d8c1751b84cb6add673acc662e4624d6697b1dc93b131'
FRAMES=80026
SAMPLES=160210944

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(8*1024*1024),b''): h.update(data)
    return h.hexdigest()

def probe(path,*args):
    return json.loads(subprocess.check_output([str(FP),'-v','error',*args,'-of','json',str(path)]))

def audio_digest(path,fmt,codec):
    p=subprocess.Popen([str(FF),'-v','error','-xerror','-i',str(path),'-map','0:a:0','-vn','-c:a',codec,'-f',fmt,'pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    h=hashlib.sha256();size=0
    for data in iter(lambda:p.stdout.read(8*1024*1024),b''):h.update(data);size+=len(data)
    errors=p.stderr.read();assert p.wait()==0,errors.decode(errors='replace')
    return {'sha256':h.hexdigest(),'bytes':size}

def main(args):
    master=Path(args.master).resolve();out=Path(args.export).resolve();dest=Path(args.receipt).resolve()
    assert sha(master)==MASTER_SHA,'Delivered master changed'
    before=sha(out)
    streams=probe(out,'-show_streams')['streams'];assert len(streams)==2,'Unexpected streams'
    v=next(s for s in streams if s['codec_type']=='video');a=next(s for s in streams if s['codec_type']=='audio')
    assert v['codec_name']=='prores' and v['width']==960 and v['height']==720
    assert Fraction(v['r_frame_rate'])==Fraction(24000,1001)
    assert v.get('sample_aspect_ratio')=='1:1' and v.get('field_order') in ('progressive','unknown',None)
    assert v['color_range']=='tv' and v['color_space']=='bt470bg','Range/matrix changed'
    assert v.get('color_primaries','unknown')=='unknown' and v.get('color_transfer','unknown')=='unknown','Unknown primaries/TRC invented'
    if args.profile=='4444':
        assert v['profile']=='4444' and v['pix_fmt'] in ('yuv444p10le','yuv444p12le')
    else:
        assert v['profile']=='HQ' and v['pix_fmt']=='yuv422p10le'
    assert a['codec_name'] in ('pcm_f32le','pcm_s24le') and int(a['sample_rate'])==48000 and a['channels']==2
    times=[];tb=Fraction(v['time_base'])
    for packet in probe(out,'-select_streams','v:0','-show_packets','-show_entries','packet=pts')['packets']:times.append(int(packet['pts'])*tb)
    assert len(times)==FRAMES and times==sorted(set(times)),'Frame loss/duplicate or unordered PTS'
    maxcad=max(abs(t-Fraction(n*1001,24000)) for n,t in enumerate(times));assert maxcad<=Fraction(1,1000000),'MOV cadence is not exact native cadence'
    sv=probe(master,'-select_streams','v:0','-show_streams')['streams'][0];stb=Fraction(sv['time_base'])
    old=[int(p['pts'])*stb for p in probe(master,'-select_streams','v:0','-show_packets','-show_entries','packet=pts')['packets']]
    assert len(old)==FRAMES
    maxsource=max(abs(x-y) for x,y in zip(times,old));assert maxsource<=Fraction(51,100000),'Source rounded timestamp discrepancy too large'
    count=0;maxaudio=Fraction(0);prev=None
    for frame in probe(out,'-select_streams','a:0','-show_frames','-show_entries','frame=pts_time,nb_samples')['frames']:
        t=Fraction(frame['pts_time']);n=int(frame['nb_samples']);assert n>0 and (prev is None or t>prev)
        maxaudio=max(maxaudio,abs(t-Fraction(count,48000)));count+=n;prev=t
    assert count==SAMPLES and maxaudio<=Fraction(1,1000),'Audio sample-clock/EOF changed'
    fmt,codec,bytes_sample=('f32le','pcm_f32le',4) if a['codec_name']=='pcm_f32le' else ('s24le','pcm_s24le',3)
    expected=audio_digest(master,fmt,codec);actual=audio_digest(out,fmt,codec)
    assert expected==actual and actual['bytes']==SAMPLES*2*bytes_sample,'PCM sample data changed'
    dest.parent.mkdir(parents=True,exist_ok=True);log=dest.with_suffix('.decode.log')
    stats=dest.with_suffix('.psnr.log')
    # Timestamp validation above remains independent: normalization here pairs
    # decoded frame indices for compression measurement, never timing acceptance.
    graph=('[0:v:0]settb=1/24000,setpts=N*1001,format=yuv444p12le[reference];'
           '[1:v:0]settb=1/24000,setpts=N*1001,format=yuv444p12le[derivative];'
           f'[derivative][reference]psnr=stats_file={stats.name}:stats_version=2:shortest=1:repeatlast=0[comparison]')
    with log.open('wb') as err:
        result=subprocess.run([str(FF),'-v','error','-xerror','-threads','8','-i',str(master),'-threads','8','-i',str(out),'-filter_threads','4','-filter_complex_threads','4','-filter_complex',graph,'-map','[comparison]','-map','1:a:0','-fps_mode','passthrough','-progress','pipe:1','-nostats','-f','null','-'],cwd=dest.parent,stdout=subprocess.PIPE,stderr=err,check=True)
    progress=dict(line.split('=',1) for line in result.stdout.decode().splitlines() if '=' in line)
    assert progress['progress']=='end' and int(progress['frame'])==FRAMES
    mse=[];psnr=[]
    with stats.open(encoding='utf-8') as f:
        for line in f:
            if not line.startswith('n:'):continue
            fields=dict(token.split(':',1) for token in line.split())
            assert int(fields['n'])==len(mse)+1,'PSNR frame index missing/duplicated'
            error=float(fields['mse_avg']);quality=float(fields['psnr_avg'])
            assert math.isfinite(error) and error>=0 and not math.isnan(quality)
            assert quality>=45,'Gross source/derivative content discrepancy'
            mse.append(error);psnr.append(quality)
    assert len(mse)==FRAMES,'Not every decoded source/derivative frame compared'
    mean_mse=math.fsum(mse)/FRAMES
    aggregate=10*math.log10(4095**2/mean_mse) if mean_mse else None
    minimum=min(psnr)
    assert sha(out)==before,'Export changed during QA'
    receipt={'status':'upload_derivative_technical_pass','verified_at':datetime.now(timezone.utc).isoformat(),'master':str(master),'master_sha256':MASTER_SHA,'export':str(out),'export_sha256':before,'streams':streams,'frames':FRAMES,'full_video_audio_decode_through_EOF':True,'maximum_ideal_video_cadence_error_seconds':float(maxcad),'maximum_difference_from_source_rounded_video_PTS_seconds':float(maxsource),'decoded_audio_samples_per_channel':count,'maximum_audio_sample_clock_error_seconds':float(maxaudio),'audio_digest':actual,'audio_comparison_scope':'Exact original float32 decoded PCM bytes' if fmt=='f32le' else 'Exact deterministic source-to-signed24 PCM conversion; original float32 byte equality is not claimed','decode_log_sha256':sha(log),'lossy_video_pixel_equality_claimed':False,'visual_review_performed':False,'color_scope':'Source limited range and BT.470BG matrix retained; primaries and transfer remain unknown. No gamut/gamma conversion or historical color authenticity claim.'}
    receipt['full_source_derivative_PSNR_comparison']={'frames':FRAMES,'alignment':'Decoded frame index; both streams settb=1/24000,setpts=N*1001. Original timestamp checks remain separate.','comparison_pixel_format':'yuv444p12le','aggregate_PSNR_dB_from_mean_reported_MSE':aggregate,'minimum_frame_average_PSNR_dB':minimum if math.isfinite(minimum) else None,'zero_MSE_all_frames':mean_mse==0,'gross_mismatch_guard_minimum_frame_average_PSNR_dB':45,'stats_file':str(stats),'stats_sha256':sha(stats),'scope':'Finite full-frame numerical compression comparison, not visual acceptance or lossless equality. Aggregate uses FFmpeg per-frame reported MSE precision.'}
    dest.write_text(json.dumps(receipt,indent=2),encoding='utf-8');print(dest,sha(dest),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--master',required=True);p.add_argument('--export',required=True);p.add_argument('--profile',choices=['4444','hq'],default='4444');p.add_argument('--receipt',required=True);main(p.parse_args())
