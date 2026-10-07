"""Independent whole-shot Y / unaffected-UV proof and every-corrected-frame contacts."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,subprocess
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from sample_native import ROOT,BASE,FF,W,H,convert_yuv
P=W*H

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for part in iter(lambda:f.read(4*1024*1024),b''):h.update(part)
    return h.hexdigest()

def reader(path):
    return subprocess.Popen([str(FF),'-v','error','-xerror','-threads','2','-filter_threads','2',
        '-i',str(path),'-an','-sn','-fps_mode','passthrough','-threads','2',
        '-pix_fmt','yuv444p','-f','rawvideo','-'],stdout=subprocess.PIPE)

def take(stream,size):
    result=bytearray()
    while len(result)<size:
        part=stream.read(size-len(result))
        if not part:raise ValueError('Short frame stream')
        result.extend(part)
    return bytes(result)

def audit(args):
    source_receipt=BASE/f'source_{args.batch}_per_shot_y.json'
    originals=json.loads(source_receipt.read_text());source=originals['shots'][args.shot]
    if getattr(args,'source_override',None):
        source=args.source_override
    map_folder=BASE/'dissolves' if args.batch=='batch_01' else BASE/'dissolves'/args.batch
    mapping_path=Path(args.mapping) if getattr(args,'mapping',None) else map_folder/'source_dissolve_map.json'
    mapping=json.loads(mapping_path.read_text())
    if mapping['source_sha256']!=originals['source_sha256']:raise ValueError('Source proof/map mismatch')
    window=next(t for t in mapping['transitions'] if t['boundary_frame']==source['start_frame'])
    begin=window['support_start_frame']-source['start_frame'];end=window['support_end_frame_exclusive']-source['start_frame']
    before_hash,after_hash=sha(args.before),sha(args.after)
    folder=BASE/'dissolves'/'corrections'/args.shot/after_hash[:12];folder.mkdir(parents=True,exist_ok=True)
    old,new=reader(args.before),reader(args.after);yhash=hashlib.sha256();uvold=hashlib.sha256();uvnew=hashlib.sha256()
    chosen=range(max(0,begin-4),min(source['frames'],end+4));samples=[];changes=[]
    for n in range(source['frames']):
        a=take(old.stdout,P*3);b=take(new.stdout,P*3);yhash.update(b[:P])
        if a[:P]!=b[:P]:raise ValueError(f'Correction changed original Y at local {n}')
        if not begin<=n<end:
            uvold.update(a[P:]);uvnew.update(b[P:])
            if a[P:]!=b[P:]:raise ValueError(f'Correction changed UV outside support at local {n}')
        elif n in chosen:
            delta=np.frombuffer(b[P:],np.uint8).astype(np.int16)-np.frombuffer(a[P:],np.uint8)
            changes.append({'frame_global':source['start_frame']+n,'mean_abs_UV_change':float(np.abs(delta).mean()),'max_abs_UV_change':int(np.abs(delta).max())})
        if n in chosen:samples.append((n,a,b))
    for process in [old,new]:
        if process.stdout.read(1):raise ValueError('Extra frames')
        process.stdout.close()
        if process.wait()!=0:raise ValueError('Decode failed')
    if yhash.hexdigest()!=source['Y_sha256']:raise ValueError('Corrected master original Y digest mismatch')
    # One conversion process for all original-neutral / previous / corrected triples.
    yuv=b''.join(chunk for _,a,b in samples for chunk in [b[:P]+bytes([128])*(P*2),a,b])
    rgb=np.frombuffer(convert_yuv(yuv),np.uint8).reshape(-1,H,W,3)
    font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',17);contacts=[];sample_records=[]
    for offset in range(0,len(samples),4):
        group=samples[offset:offset+4];board=Image.new('RGB',(960,276*len(group)),'#151515');draw=ImageDraw.Draw(board)
        for j,(n,a,b) in enumerate(group):
            for col,label in enumerate(['SOURCE Y','BEFORE','CORRECTED']):
                arr=rgb[3*(offset+j)+col];img=Image.fromarray(arr);x,y=col*320,j*276
                board.paste(img.resize((320,240),Image.Resampling.LANCZOS),(x,y+32))
                draw.text((x+4,y+3),f'{label} G{source["start_frame"]+n}',font=font,fill='white')
                if col==2:
                    target=folder/f'global_{source["start_frame"]+n:06d}.png';img.save(target)
                    sample_records.append({'global_frame':source['start_frame']+n,'corrected_native_frame':str(target)})
        target=folder/f'contact_{offset//4:02d}.jpg';board.save(target,quality=97);contacts.append(str(target))
    report={'schema_version':1,'shot_id':args.shot,'status':'independent_integrity_pass_visual_review_pending',
            'verified_at':datetime.now(timezone.utc).isoformat(),'before':str(Path(args.before).resolve()),'before_sha256':before_hash,
            'after':str(Path(args.after).resolve()),'after_sha256':after_hash,'support':[source['start_frame']+begin,source['start_frame']+end],
            'full_frames':source['frames'],'exact_original_Y_all_frames':True,'source_Y_sha256':yhash.hexdigest(),
            'exact_UV_outside_support':uvold.hexdigest()==uvnew.hexdigest(),'outside_UV_sha256':uvnew.hexdigest(),
            'batch_id':args.batch,'source_digest_receipt':str(source_receipt),'source_digest_override':getattr(args,'source_override',None),'changes':changes,'samples':sample_records,'contact_sheets':contacts,
            'delivery_acceptance':False,'scope':'All original Y bytes and all unaffected UV bytes compared. Every support frame plus trailing margin saved for visual review; audio and playback remain pending.'}
    (folder/'integrity_and_samples.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'shot':args.shot,'status':report['status'],'frames':source['frames'],'sampled_frames':len(samples),'folder':str(folder)}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--shot',required=True);p.add_argument('--before',required=True);p.add_argument('--after',required=True)
    p.add_argument('--batch',default='batch_01')
    p.add_argument('--mapping')
    audit(p.parse_args())
