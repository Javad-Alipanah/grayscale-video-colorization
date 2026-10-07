"""Stream reviewed podium methods into unselected whole-shot material candidates."""
from pathlib import Path
import sys,copy,contextlib,hashlib,shutil
import numpy as np
from PIL import Image,ImageDraw,ImageOps
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
import production as p
import delivery as d
from render_crest_trial import encode
from prepare_comparison import apply,alphas,rgb,P,SCOPES
STATUS=ROOT/'temporal_candidate_status.json'
REVIEWS={
 'podium_source_geometry_review.json':'50d3d7eb0260e1fee435cc079468db60b96d2fa4e4621dc8dcbf3f6cb8948f3d',
 'podium_material_comparison_v01/visual_review.json':'545957e32ef4d9137691dc833d0397493b13b872bec2d9320a893eb09738000b',
 'podium_entry_comparison_v01/visual_review.json':'fcc5797b4294172be79cba7d2f76274575ff6a15f64ecdcb7fe4f3ba10f7bd4a'}
def status(stage,**details):p.atomic_json(STATUS,dict(stage=stage,updated_at=p.utc(),selection_changed=False,delivery_acceptance=False,**details))
def run(shot):
 reviews=[]
 for name,sha in REVIEWS.items():
  path=p.PROJECT/'scenes/qc/material_disposition_v1'/name
  if p.sha256(path)!=sha:raise ValueError('Independent method review changed')
  reviews.append(dict(path=str(path),sha256=sha))
 gp=p.PROJECT/'scenes/qc/material_disposition_v1/podium_geometry_worker'/shot/'geometry_proposal.json'
 if p.sha256(gp)!=SCOPES[shot][0]:raise ValueError('Source geometry changed')
 geometry=p.read_json(gp);rows={r['frame_global']:r for r in geometry['frames']}
 prior_path=Path(p.read_json(p.HERE/'source_y_overrides.json')[shot]['receipt']);prior=p.read_json(prior_path)
 if p.sha256(prior['output'])!=prior['output_sha256'] or p.sha256(geometry['source_cache'])!=geometry['source_cache_sha256']:raise ValueError('Bound media changed')
 ready_path=p.PROJECT/'scenes/qc/projection_masks'/shot/'mask_ready.json';ready=p.read_json(ready_path)
 mask_path=p.WORKSPACE/ready['mask_path']
 if ready['status']!='source_mask_native_review_pass' or p.sha256(mask_path)!=ready['mask_sha256']:raise ValueError('Scientific source mask changed')
 entry_path=ROOT/'entry_comparison_v01/trial.json';entry=p.read_json(entry_path)
 patches={r['frame_global']:r for r in entry['records']} if shot=='shot_058480' else {}
 if patches and entry['prior_selected_output_sha256']!=prior['output_sha256']:raise ValueError('Reviewed entry prior differs')
 for row in patches.values():
  if p.sha256(row['output'])!=row['output_sha256']:raise ValueError('Reviewed entry payload changed')
 fingerprint=p.json_digest(dict(prior=p.sha256(prior_path),geometry=p.sha256(gp),entry=p.sha256(entry_path) if patches else None,reviews=reviews,implementation=p.sha256(__file__),method=p.sha256(ROOT/'prepare_comparison.py')))
 out=d.BASE/'material_trials'/shot/('podium_'+fingerprint[:16]);out.mkdir(parents=True,exist_ok=True)
 receipt=out/'treatment.json';output=out/'source_y_master.mkv';alpha_path=out/'material_support_ffv1.mkv'
 if receipt.exists() and p.sha256(output)==p.read_json(receipt)['output_sha256']:return str(receipt)
 if shutil.disk_usage(p.WORKSPACE).free/2**30<10+1.3*(Path(prior['output']).stat().st_size/2**30+.5):raise ValueError('Unchanged reserve would be violated')
 source=p.read_json(p.HERE/'batch_05_manifest.json')['source'];support=set(prior.get('verified_support_union_global',[]))
 transition=prior.get('transition',{})
 support.update(range(transition.get('support_start_frame',0),transition.get('support_end_frame_exclusive',0)))
 modified=[];records=[];yh=hashlib.sha256();payload=hashlib.sha256();ah=hashlib.sha256();unchanged=hashlib.sha256()
 sample_range=range(58480,58609) if shot=='shot_058480' else range(59420,59577)
 contacts=[];contact_no=0;review_dir=out/'native_review';review_dir.mkdir(exist_ok=True)
 with p.ExclusiveLock(p.HERE/'boundary_chroma.lock',wait=True),p.ExclusiveLock(p.HERE/'delivery_queue.lock',wait=True):
  if p.read_json(p.HERE/'source_y_overrides.json')[shot]['receipt']!=str(prior_path):raise ValueError('Selected prior changed')
  with (out/'media.log').open('w') as log:
   readers=[d.decoder(prior['output'],'yuv444p',log),d.decoder(geometry['source_cache'],'yuv444p',log,prior['start_frame']-geometry['source_frame_mapping'],prior['frames']),d.decoder(mask_path,'gray',log,prior['start_frame']-ready['start_frame'],prior['frames'])]
   writer=encode(output,source,'yuv444p',log);awriter=encode(alpha_path,source,'gray',log)
   try:
    for i in range(prior['frames']):
     frame=prior['start_frame']+i;raw=d.read_exact(readers[0].stdout,P*3);native=d.read_exact(readers[1].stdout,P*3);mr=d.read_exact(readers[2].stdout,P)
     if len(raw)!=P*3 or len(native)!=P*3 or len(mr)!=P:raise ValueError('Short native input')
     b=np.frombuffer(raw,np.uint8).reshape(3,720,960);s=np.frombuffer(native,np.uint8).reshape(3,720,960);m=np.frombuffer(mr,np.uint8).reshape(720,960)
     if not np.array_equal(b[0],s[0]):raise ValueError('Prior originalY differs')
     after,weights=apply(b,s,rows.get(frame,{}));active=np.any(weights>0,axis=0)
     if frame in patches:
      after=np.frombuffer(Path(patches[frame]['output']).read_bytes(),np.uint8).reshape(3,720,960)
      active=np.any(alphas(rows[58484])>0,axis=0) if patches[frame]['incoming_alpha']>0 else np.zeros((720,960),bool)
     if not np.array_equal(after[0],s[0]) or not np.array_equal(after[1:,~active],b[1:,~active]):raise ValueError('ExactY/outside material support invariant failed')
     if not np.array_equal(after[1:,m>0],b[1:,m>0]):raise ValueError('Material correction modifies protected scientific field')
     changed=int(np.count_nonzero(np.any(after[1:]!=b[1:],axis=0)))
     if changed:modified.append(frame);support.add(frame)
     else:unchanged.update(after.tobytes())
     ar=(active.astype(np.uint8)*255).tobytes();result=after.tobytes();yh.update(result[:P]);payload.update(result);ah.update(ar);writer.stdin.write(result);awriter.stdin.write(ar)
     records.append(dict(frame_global=frame,changed_uv_pixels=changed,material_support_pixels=int(active.sum()),scientific_field_unchanged=True))
     if frame in sample_range:
      images=[rgb(v.tobytes()) for v in [s,b,after]];png=review_dir/f'candidate_{frame:06d}.png';images[2].save(png)
      crop=(480,340,960,720) if shot=='shot_058480' else (560,340,960,720)
      tile=Image.new('RGB',(1440,405));ImageDraw.Draw(tile).text((4,4),f'G{frame} source | selected | podium candidate; native-scale crop',fill='white')
      for j,img in enumerate(images):
       piece=img.crop(crop);tile.paste(piece,(j*480+(480-piece.width)//2,25))
      contacts.append(tile)
      if len(contacts)==4 or frame==sample_range.stop-1:
       sheet=Image.new('RGB',(1440,405*len(contacts)))
       for j,t in enumerate(contacts):sheet.paste(t,(0,j*405))
       sheet.save(review_dir/f'contact_{contact_no:03d}.jpg',quality=95);contact_no+=1;contacts=[]
     if i%32==0:status('composing_podium_material_candidate',shot_id=shot,done=i+1,total=prior['frames'])
    if any(r.stdout.read(1) for r in readers):raise ValueError('Excess native input')
   finally:
    for r in readers:r.stdout.close()
    for w in [writer,awriter]:
     with contextlib.suppress(OSError):w.stdin.close()
    codes=[c.wait() for c in readers+[writer,awriter]]
   if any(codes):raise ValueError('Media process failed')
  if yh.hexdigest()!=prior['y_sha256']:raise ValueError('Full originalY digest changed')
  status('verifying_podium_material_candidate',shot_id=shot)
  verified=hashlib.sha256();va=hashlib.sha256()
  with (out/'verify.log').open('w') as log:
   vr=d.decoder(output,'yuv444p',log);ar=d.decoder(alpha_path,'gray',log)
   try:
    for _ in range(prior['frames']):
     v=d.read_exact(vr.stdout,P*3);a=d.read_exact(ar.stdout,P)
     if len(v)!=P*3 or len(a)!=P:raise ValueError('Short encoded candidate')
     verified.update(v);va.update(a)
    if vr.stdout.read(1) or ar.stdout.read(1):raise ValueError('Excess encoded candidate')
   finally:vr.stdout.close();ar.stdout.close();codes=[vr.wait(),ar.wait()]
   if any(codes) or verified.hexdigest()!=payload.hexdigest() or va.hexdigest()!=ah.hexdigest():raise ValueError('Encoded payload differs')
  result=copy.deepcopy(prior)
  result.update(status='draft_verified',quality_acceptance='native_temporal_material_review_pending',method='Reviewed native wood-palette/source-neutral printed crest within source contours, including incoming-field treatment before source alpha; exact originalY',fingerprint=fingerprint,output=str(output),output_sha256=p.sha256(output),full_yuv_sha256=verified.hexdigest(),y_sha256=yh.hexdigest(),material_alpha=str(alpha_path),material_alpha_sha256=p.sha256(alpha_path),material_alpha_decoded_sha256=ah.hexdigest(),material_alpha_semantics='Binary support for this compound material correction only; numerical wood/crest weights remain in bound method.',material_prior_receipt=str(prior_path),material_prior_receipt_sha256=p.sha256(prior_path),material_prior_output=prior['output'],material_prior_output_sha256=prior['output_sha256'],material_geometry=str(gp),material_geometry_sha256=p.sha256(gp),method_reviews=reviews,entry_trial=str(entry_path) if patches else None,entry_trial_sha256=p.sha256(entry_path) if patches else None,source_cache=geometry['source_cache'],source_cache_sha256=geometry['source_cache_sha256'],source_clip_start_frame=geometry['source_frame_mapping'],scientific_mask_ready=str(ready_path),scientific_mask_ready_sha256=p.sha256(ready_path),exact_source_y=True,exact_outside_support_uv=True,exact_uv_outside_material_alpha=True,exact_scientific_field_preserved=True,full_decode_verified=True,verified_support_union_global=sorted(support),material_changed_frames=modified,unchanged_frame_yuv_sha256=unchanged.hexdigest(),native_review_directory=str(review_dir),native_review_frames=list(sample_range),timing=d.verify_timestamps(output,prior['frames'],source),selection_changed=False,delivery_acceptance=False,finished_at=p.utc(),limitations=['Full temporal candidate requires independent native review before selection.','Source-inset thin ledges and physical edge slivers are deliberately preserved.','Continuous viewing is deferred to the user by instruction; technical/scoped QA remains required.'])
  result.pop('outside_support_uv_sha256',None)
  result['exact_previous_treatment_preserved']=not bool(patches)
  if patches:result['prior_entrance_refined_before_alpha']=True;result['exact_prior_disjoint_joint_preserved']=True
  d.verify_video_geometry(output,source);p.atomic_json(out/'per_frame_measurements.json',records);p.atomic_json(receipt,result)
 return str(receipt)
def main():
 results={}
 for shot in SCOPES:
  results[shot]=run(shot);status('candidate_ready_pending_native_QA',completed=results)
 status('all_podium_candidates_ready_pending_native_QA',completed=results)
if __name__=='__main__':
 try:main()
 except BaseException as e:status('failed',error=str(e));raise
