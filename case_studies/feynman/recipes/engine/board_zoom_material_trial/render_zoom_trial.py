"""Versioned unselected full source-Y zoom board trial with bounded source masks."""
from pathlib import Path
import sys,copy,hashlib,contextlib,shutil,subprocess,argparse
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT.parent))
import production as p
import delivery as d
from render_crest_trial import encode
from zoom_material import alpha
P=960*720
def status(stage,**kw):p.atomic_json(ROOT/'full_trial_status.json',dict(stage=stage,updated_at=p.utc(),selection_changed=False,delivery_acceptance=False,**kw))
def rgb(raw):
 return Image.frombytes('RGB',(960,720),subprocess.run([str(p.FFMPEG),'-v','error','-f','rawvideo','-pix_fmt','yuv444p','-s','960x720','-color_range','tv','-colorspace','bt470bg','-i','pipe:0','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],input=raw,capture_output=True,check=True).stdout)
def main(review_path):
 reviews=p.read_json(review_path);assert reviews['source_geometry_and_foreground_trial_supported'] is True
 for evidence in reviews['evidence']:assert p.sha256(evidence['path'])==evidence['sha256']
 map_path=ROOT/'combined_foreground_v01.json';mapping=p.read_json(map_path);assert p.sha256(map_path)==reviews['foreground_map_sha256']
 gp=ROOT/'physical_geometry_worker/source_edges_v07/geometry_proposal.json';assert p.sha256(gp)==reviews['physical_geometry_sha256']=='fc50fbe9484ac5250828a070723a7fe43922f44c4fcfa3e35e87aa5ab04b8f47'
 rows={r['frame_global']:r for r in mapping['frames']};panels={r['frame_global']:r for r in p.read_json(gp)['frames']};assert set(rows)==set(range(27193,28464))
 for row in rows.values():assert p.sha256(row['mask_path'])==row['mask_sha256']
 choice=p.read_json(p.HERE/'source_y_overrides.json')['shot_026165'];prior_path=Path(choice['receipt']);prior=p.read_json(prior_path)
 assert prior['start_frame']==26165 and prior['frames']==2299 and p.sha256(prior['output'])==prior['output_sha256']
 crest_path=Path(prior['bounded_trial']);assert p.sha256(crest_path)==prior['bounded_trial_sha256'];crest=p.read_json(crest_path);assert p.sha256(crest['alpha'])==crest['alpha_sha256']
 fp=p.json_digest(dict(prior=p.sha256(prior_path),mapping=p.sha256(map_path),geometry=p.sha256(gp),review=p.sha256(review_path),implementation=p.sha256(__file__),alpha=p.sha256(ROOT/'zoom_material.py')))
 out=d.BASE/'material_trials/shot_026165'/('board_zoom_'+fp[:16]);out.mkdir(parents=True,exist_ok=True)
 receipt=out/'treatment.json';output=out/'source_y_master.mkv';ap=out/'material_alpha_ffv1.mkv'
 if receipt.exists() and p.sha256(output)==p.read_json(receipt)['output_sha256']:status('candidate_ready_pending_native_QA',receipt=str(receipt));return
 assert shutil.disk_usage(p.WORKSPACE).free/2**30>10+1.3*(Path(prior['output']).stat().st_size/2**30+1)
 source=p.read_json(p.PROJECT/'scenes/second_batch_manifest.json')['source'];target=np.array([125,124],np.float32)[:,None,None]
 yh=hashlib.sha256();vh=hashlib.sha256();ah=hashlib.sha256();measure=[];modified=[];unchanged=hashlib.sha256();support=set(prior.get('verified_support_union_global',[]));tr=prior.get('transition',{});support.update(range(tr.get('support_start_frame',0),tr.get('support_end_frame_exclusive',0)))
 with p.ExclusiveLock(p.HERE/'boundary_chroma.lock',wait=True),p.ExclusiveLock(p.HERE/'delivery_queue.lock',wait=True):
  assert p.read_json(p.HERE/'source_y_overrides.json')['shot_026165']==choice
  with (out/'media.log').open('w') as log:
   reader=d.decoder(prior['output'],'yuv444p',log);cr=d.decoder(crest['alpha'],'gray',log);writer=encode(output,source,'yuv444p',log);aw=encode(ap,source,'gray',log)
   try:
    for i in range(prior['frames']):
     g=prior['start_frame']+i;raw=d.read_exact(reader.stdout,P*3);assert len(raw)==P*3;b=np.frombuffer(raw,np.uint8).reshape(3,720,960);a=np.zeros((720,960),np.uint8)
     if g in rows:
      core=np.array(Image.open(rows[g]['mask_path']).convert('L'));a,guard=alpha(b,panels[g],core);assert not a[guard].any()
     if crest['start_frame']<=g<crest['end_frame']:
      cb=d.read_exact(cr.stdout,P);assert len(cb)==P;cm=np.frombuffer(cb,np.uint8).reshape(720,960)>0
      assert not a[cm].any(),'Board alpha overlaps reviewed printed crest'
     w=a.astype(np.float32)/255;c=b.copy();c[1:]=np.rint(b[1:].astype(np.float32)*(1-w)+target*w).clip(0,255).astype(np.uint8)
     assert np.array_equal(c[0],b[0]) and np.array_equal(c[1:,a==0],b[1:,a==0])
     changed=int(np.count_nonzero(np.any(c[1:]!=b[1:],axis=0)))
     if changed:modified.append(g);support.add(g)
     else:unchanged.update(c.tobytes())
     data=c.tobytes();ar=a.tobytes();yh.update(data[:P]);vh.update(data);ah.update(ar);writer.stdin.write(data);aw.stdin.write(ar)
     measure.append(dict(frame_global=g,changed_pixels=changed,alpha_pixels=int(np.count_nonzero(a)),source_actor_guard_unchanged=True,held_issues=rows.get(g,{}).get('issues',[])))
     if i%64==0:status('rendering_unselected_zoom_board',done=i+1,total=prior['frames'])
    assert not reader.stdout.read(1) and not cr.stdout.read(1)
   finally:
    reader.stdout.close();cr.stdout.close()
    for r in [writer,aw]:
     with contextlib.suppress(OSError):r.stdin.close()
    assert all(r.wait()==0 for r in [reader,cr,writer,aw])
  assert yh.hexdigest()==prior['y_sha256']
  status('verifying_full_zoom_trial_decode')
  verified=hashlib.sha256();va=hashlib.sha256()
  with (out/'verify.log').open('w') as log:
   r=d.decoder(output,'yuv444p',log);ar=d.decoder(ap,'gray',log)
   try:
    for i in range(prior['frames']):
     raw=d.read_exact(r.stdout,P*3);a=d.read_exact(ar.stdout,P);assert len(raw)==P*3 and len(a)==P;verified.update(raw);va.update(a)
    assert not r.stdout.read(1) and not ar.stdout.read(1)
   finally:r.stdout.close();ar.stdout.close();assert r.wait()==0 and ar.wait()==0
  assert verified.hexdigest()==vh.hexdigest() and va.hexdigest()==ah.hexdigest()
  record=copy.deepcopy(prior);record.update(status='draft_verified',fingerprint=fp,output=str(output),output_sha256=p.sha256(output),full_yuv_sha256=vh.hexdigest(),y_sha256=yh.hexdigest(),method='Source-board union and reviewed actor guards; existing gray-olive palette applied only to warm UV, originalY exact',quality_acceptance='native_temporal_material_review_pending',material_prior_receipt=str(prior_path),material_prior_receipt_sha256=p.sha256(prior_path),material_prior_output=prior['output'],material_prior_output_sha256=prior['output_sha256'],material_alpha=str(ap),material_alpha_sha256=p.sha256(ap),material_alpha_decoded_sha256=ah.hexdigest(),material_changed_frames=modified,material_unchanged_frame_yuv_sha256=unchanged.hexdigest(),verified_support_union_global=sorted(support),foreground_map=str(map_path),foreground_map_sha256=p.sha256(map_path),physical_geometry=str(gp),physical_geometry_sha256=p.sha256(gp),source_trial_review=str(review_path),source_trial_review_sha256=p.sha256(review_path),exact_original_Y=True,exact_source_y=True,full_decode_verified=True,exact_outside_support_uv=True,exact_UV_outside_material_alpha=True,exact_prior_onset_and_170crest_YUV=True,source_actor_guard_unchanged=True,timing=d.verify_timestamps(output,prior['frames'],source),finished_at=p.utc(),selection_changed=False,delivery_acceptance=False,limitations=['Unselected temporal color trial; all affected board/actor boundaries and onset/exit require independent native QA.','Conservative8px actor guards and source-inset frames/rails retain uncertain edge chroma.','Full continuous viewing explicitly deferred to user.'])
  for old_key in ['outside_support_uv_sha256','exact_prior_onset_and_170crest_YUV','exact_prior_onset_and_all_outside_crest_yuv','exact_reviewed_crest_patch_yuv','crest_patch_yuv_sha256','all_outside_crest_yuv_sha256']:record.pop(old_key,None)
  record.update(exact_prior_six_frame_onset_YUV=True,exact_printed_crest_UV_on_all170_source_alpha_fields=True,crest_alpha=str(crest['alpha']),crest_alpha_sha256=crest['alpha_sha256'],crest_alpha_range=[crest['start_frame'],crest['end_frame']],prior_170frame_fullYUV_preservation_scope='Only the source-alpha crest pixels remain byte-identical; board pixels outside that spatial support may change in overlapping frames.')
  d.verify_video_geometry(output,source);p.atomic_json(out/'per_frame_measurements.json',measure);p.atomic_json(receipt,record)
 status('candidate_ready_pending_native_QA',receipt=str(receipt),output_sha256=record['output_sha256'])
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--source-review',type=Path,required=True);args=ap.parse_args()
 try:main(args.source_review)
 except BaseException as e:status('failed',error=str(e));raise
