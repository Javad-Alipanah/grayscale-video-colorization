"""Compose reviewed source-soft coat-edge method with unselected podium candidate."""
from pathlib import Path
import sys,hashlib,copy,contextlib,shutil
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT.parent));sys.path.insert(0,str(ROOT.parent/'podium_material_trial'))
import production as p
import delivery as d
from render_crest_trial import encode
from prepare_comparison import rgb,P
STATUS=ROOT/'expanded_candidate_status.json'
def status(stage,**kw):p.atomic_json(STATUS,dict(stage=stage,updated_at=p.utc(),selection_changed=False,delivery_acceptance=False,**kw))
def main():
 gp=p.PROJECT/'scenes/qc/material_disposition_v1/coat_fringe_059176/expanded_source_worker_v2/geometry_trial.json'
 review=gp.parent/'independent_source_review_sol.json'
 assert p.sha256(gp)=='75e639d725663fdabded687bb8acce1c6693e2d85a70f52f2bc09fd49fb67abb'
 assert p.sha256(review)=='deca0994e2149a27c5b1152e882aa9d839a601711c2664a6e688a456b3644b7d'
 geometry=p.read_json(gp);mapping={r['frame_global']:r for r in geometry['records']}
 assert set(mapping)==set(range(59179,59364))|set(range(59598,59637))
 for row in mapping.values():assert p.sha256(row['alpha_path'])==row['alpha_sha256']
 prior_path=Path(p.read_json(p.HERE/'podium_material_trial/temporal_candidate_status.json')['completed']['shot_059176']);prior=p.read_json(prior_path)
 assert p.sha256(prior['output'])==prior['output_sha256'] and p.sha256(prior['material_alpha'])==prior['material_alpha_sha256']
 assert p.sha256(prior['source_cache'])==prior['source_cache_sha256']
 fingerprint=p.json_digest(dict(prior=p.sha256(prior_path),geometry=p.sha256(gp),review=p.sha256(review),method=p.sha256(__file__)))
 out=d.BASE/'material_trials/shot_059176'/('podium_coat_'+fingerprint[:16]);out.mkdir(parents=True,exist_ok=True)
 output=out/'source_y_master.mkv';mask_path=out/'material_support_ffv1.mkv';receipt=out/'treatment.json'
 if receipt.exists() and p.sha256(output)==p.read_json(receipt)['output_sha256']:status('compound_coat_podium_ready_pending_native_QA',receipt=str(receipt));return
 if shutil.disk_usage(p.WORKSPACE).free/2**30<10+1.3*(Path(prior['output']).stat().st_size/2**30+.5):raise ValueError('Reserve violated')
 source=p.read_json(p.HERE/'batch_05_manifest.json')['source'];frames=prior['frames'];records=[];modified=[];payload=hashlib.sha256();yh=hashlib.sha256();ah=hashlib.sha256();unchanged=hashlib.sha256()
 rd=out/'native_review';rd.mkdir(exist_ok=True);tiles=[];sheet_no=0
 sample=set(mapping)|set(range(59176,59179))|set(range(59364,59368))|set(range(59594,59598))
 with p.ExclusiveLock(p.HERE/'boundary_chroma.lock',wait=True),p.ExclusiveLock(p.HERE/'delivery_queue.lock',wait=True):
  with (out/'media.log').open('w') as log:
   readers=[d.decoder(prior['output'],'yuv444p',log),d.decoder(prior['source_cache'],'yuv444p',log,prior['start_frame']-prior['source_clip_start_frame'],frames),d.decoder(prior['material_alpha'],'gray',log)]
   writer=encode(output,source,'yuv444p',log);awriter=encode(mask_path,source,'gray',log)
   try:
    for i in range(frames):
     frame=prior['start_frame']+i;braw=d.read_exact(readers[0].stdout,P*3);sraw=d.read_exact(readers[1].stdout,P*3);ma=d.read_exact(readers[2].stdout,P)
     if len(braw)!=P*3 or len(sraw)!=P*3 or len(ma)!=P:raise ValueError('Short input')
     b=np.frombuffer(braw,np.uint8).reshape(3,720,960);s=np.frombuffer(sraw,np.uint8).reshape(3,720,960);a=np.zeros((720,960),np.uint8)
     if frame in mapping:
      r=mapping[frame];a=np.array(Image.open(r['alpha_path']).convert('L'));assert hashlib.sha256(s[0].tobytes()).hexdigest()==r['source_Y_sha256']
     old_mask=np.frombuffer(ma,np.uint8).reshape(720,960)
     assert not np.any((old_mask>0)&(a>0)),'Material supports unexpectedly overlap'
     weight=a.astype(np.float32)/255;after=b.copy();after[1:]=np.rint(b[1:].astype(np.float32)*(1-weight)+s[1:].astype(np.float32)*weight).clip(0,255).astype(np.uint8)
     assert np.array_equal(after[0],s[0]) and np.array_equal(after[1:,a==0],b[1:,a==0])
     changed=int(np.count_nonzero(np.any(after[1:]!=b[1:],axis=0)))
     if changed:modified.append(frame)
     else:unchanged.update(after.tobytes())
     ar=(((old_mask>0)|(a>0))*255).astype(np.uint8).tobytes();raw=after.tobytes();payload.update(raw);yh.update(raw[:P]);ah.update(ar);writer.stdin.write(raw);awriter.stdin.write(ar)
     records.append(dict(frame_global=frame,changed_pixels=changed,coat_alpha_pixels=int(np.count_nonzero(a))))
     if frame in sample:
      imgs=[rgb(x.tobytes()) for x in [s,b,after]];png=rd/f'candidate_{frame:06d}.png';imgs[2].save(png)
      ys,xs=np.nonzero(a);crop=(max(0,int(xs.min())-24),max(0,int(ys.min())-24),min(960,int(xs.max())+25),720) if len(xs) else (680,390,940,720)
      tile=Image.new('RGB',(900,380));ImageDraw.Draw(tile).text((4,4),f'G{frame} source | podium candidate | coat+podium; native1:1 crop {crop}',fill='white')
      for j,img in enumerate(imgs):
       part=img.crop(crop);assert part.width<=300 and part.height<=355;tile.paste(part,(j*300+(300-part.width)//2,25))
      tiles.append(tile)
      if len(tiles)==4 or frame==max(sample):
       sheet=Image.new('RGB',(900,380*len(tiles)))
       for j,t in enumerate(tiles):sheet.paste(t,(0,j*380))
       sheet.save(rd/f'contact_{sheet_no:03d}.jpg',quality=95);sheet_no+=1;tiles=[]
     if i%32==0:status('composing_expanded_coat_with_podium',done=i+1,total=frames)
    if any(r.stdout.read(1) for r in readers):raise ValueError('Excess input')
   finally:
    for r in readers:r.stdout.close()
    for w in [writer,awriter]:
     with contextlib.suppress(OSError):w.stdin.close()
    codes=[c.wait() for c in readers+[writer,awriter]]
   if any(codes):raise ValueError('Media process failed')
  assert yh.hexdigest()==prior['y_sha256']
  status('verifying_compound_coat_podium')
  vh=hashlib.sha256();va=hashlib.sha256()
  with (out/'verify.log').open('w') as log:
   r=d.decoder(output,'yuv444p',log);ar=d.decoder(mask_path,'gray',log)
   try:
    for _ in range(frames):
     raw=d.read_exact(r.stdout,P*3);mask=d.read_exact(ar.stdout,P);assert len(raw)==P*3 and len(mask)==P;vh.update(raw);va.update(mask)
    assert not r.stdout.read(1) and not ar.stdout.read(1)
   finally:r.stdout.close();ar.stdout.close();assert r.wait()==0 and ar.wait()==0
  assert vh.hexdigest()==payload.hexdigest() and va.hexdigest()==ah.hexdigest()
  record=copy.deepcopy(prior);record.update(fingerprint=fingerprint,output=str(output),output_sha256=p.sha256(output),full_yuv_sha256=vh.hexdigest(),material_alpha=str(mask_path),material_alpha_sha256=p.sha256(mask_path),material_alpha_decoded_sha256=ah.hexdigest(),compound_podium_receipt=str(prior_path),compound_podium_receipt_sha256=p.sha256(prior_path),compound_podium_output_sha256=prior['output_sha256'],coat_geometry=str(gp),coat_geometry_sha256=p.sha256(gp),coat_source_review=str(review),coat_source_review_sha256=p.sha256(review),coat_changed_frames=modified,exact_podium_payloads_preserved=True,exact_prior59178_preserved=True,exact_UV_outside_coat_alpha_to_podium=True,coat_unchanged_frame_yuv_sha256=unchanged.hexdigest(),verified_support_union_global=sorted(set(prior['verified_support_union_global'])|set(modified)),method='Reviewed native podium material plus bounded source-soft screen-facing coat-edge UV; originalY and prior source mixtures exact',native_review_directory=str(rd),native_review_frames=sorted(sample),timing=d.verify_timestamps(output,frames,source),finished_at=p.utc(),quality_acceptance='expanded_coat_and_podium_native_review_pending',limitations=['Expanded source geometry is reviewed for trial; actual-color temporal/margins remain required.','Weak/ambiguous rows stay unchanged; no fixed guard erosion, no outgoing>=59637 extension.','Full continuous viewing deferred to user, not claimed passed.'])
  d.verify_video_geometry(output,source);p.atomic_json(out/'per_frame_measurements.json',records);p.atomic_json(receipt,record)
 status('compound_coat_podium_ready_pending_native_QA',receipt=str(receipt),output_sha256=record['output_sha256'])
if __name__=='__main__':
 try:main()
 except BaseException as e:status('failed',error=str(e));raise
