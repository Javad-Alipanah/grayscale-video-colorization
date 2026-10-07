"""Compose exactly fourteen reviewed clear-back payloads into the reviewed board trial."""
from pathlib import Path
import sys,copy,contextlib,hashlib,shutil
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
import production as p
import delivery as d
from render_crest_trial import encode
P=960*720
STATUS=ROOT/'compound_candidate_status.json'
def status(stage,**kw):p.atomic_json(STATUS,dict(stage=stage,updated_at=p.utc(),selection_changed=False,delivery_acceptance=False,**kw))
def main():
 trial_path=ROOT/'back_temporal_v03/trial.json';trial=p.read_json(trial_path)
 worker=p.PROJECT/'reference-jobs/worker/batch06_output_review/board_mapping/actual_color_v01_review/narrow_back_v03_visual_review_worker.json'
 if p.sha256(worker)!='30eeb533710b8075ca8fa4095a23c62c623e4ec1edb14a77c8d43748430ae992':raise ValueError('Frozen narrow-back native review changed')
 broad_path=Path(trial['broad_receipt']);broad=p.read_json(broad_path)
 broad_review=p.PROJECT/'scenes/qc/board_material_trial/bc5f3ab44be1/visual_review.json'
 if p.sha256(broad_review)!='c1c00f99167904893fb1148b2776d1cbaaadeaf006c380b51c7cbef26feb59b5':raise ValueError('Broad board review changed')
 if p.sha256(broad_path)!=trial['broad_receipt_sha256'] or p.sha256(broad['output'])!=trial['broad_output_sha256']:raise ValueError('Broad media changed')
 patches={r['frame_global']:r for r in trial['records']}
 if set(patches)!=(set(range(76585,76592))|set(range(77159,77166))):raise ValueError('Patch scope differs')
 for frame,row in patches.items():
  raw=trial_path.parent/f'trial_{frame:06d}.yuv'
  if p.sha256(raw)!=row['native_payload_sha256'] or p.sha256(row['trial_png'])!=row['trial_png_sha256']:raise ValueError('Reviewed patch changed')
 fingerprint=p.json_digest(dict(broad=p.sha256(broad_path),trial=p.sha256(trial_path),review=p.sha256(worker),implementation=p.sha256(__file__)))
 out=d.BASE/'material_trials/shot_074465'/('board_back_'+fingerprint[:16]);out.mkdir(parents=True,exist_ok=True)
 output=out/'source_y_master.mkv';alpha_path=out/'material_support_ffv1.mkv';receipt=out/'treatment.json'
 if receipt.exists() and p.sha256(output)==p.read_json(receipt)['output_sha256']:
  status('compound_candidate_ready_pending_independent_QA',receipt=str(receipt));return
 if shutil.disk_usage(p.WORKSPACE).free/2**30<10+1.3*(Path(broad['output']).stat().st_size/2**30+.1):raise ValueError('Storage reserve would be violated')
 source=p.read_json(p.HERE/'batch_06_manifest.json')['source']
 yh=hashlib.sha256();payload=hashlib.sha256();ah=hashlib.sha256();unchanged=hashlib.sha256();patched=hashlib.sha256()
 with p.ExclusiveLock(p.HERE/'boundary_chroma.lock',wait=True),p.ExclusiveLock(p.HERE/'delivery_queue.lock',wait=True):
  with (out/'media.log').open('w') as log:
   reader=d.decoder(broad['output'],'yuv444p',log);mask_reader=d.decoder(broad['material_alpha'],'gray',log)
   writer=encode(output,source,'yuv444p',log);mask_writer=encode(alpha_path,source,'gray',log)
   try:
    for i in range(broad['frames']):
     frame=broad['start_frame']+i;before=d.read_exact(reader.stdout,P*3);oldalpha=d.read_exact(mask_reader.stdout,P)
     if len(before)!=P*3 or len(oldalpha)!=P:raise ValueError('Short input decode')
     after=before;alpha=(np.frombuffer(oldalpha,np.uint8)>0).reshape(720,960)
     if frame in patches:
      after=(trial_path.parent/f'trial_{frame:06d}.yuv').read_bytes();delta=np.array(Image.open(trial_path.parent/f'delta_{frame:06d}.png'))>0
      if after[:P]!=before[:P]:raise ValueError('Patch changes source Y')
      a=np.frombuffer(after[P:],np.uint8).reshape(2,720,960);b=np.frombuffer(before[P:],np.uint8).reshape(2,720,960)
      if not np.array_equal(a[:,~delta],b[:,~delta]):raise ValueError('Patch changes outside reviewed delta')
      alpha=alpha|delta;patched.update(after)
     else:unchanged.update(after)
     rawalpha=(alpha*255).astype(np.uint8).tobytes();yh.update(after[:P]);payload.update(after);ah.update(rawalpha)
     writer.stdin.write(after);mask_writer.stdin.write(rawalpha)
     if i%64==0:status('composing_reviewed_board_and_back',done=i+1,total=broad['frames'])
    if reader.stdout.read(1) or mask_reader.stdout.read(1):raise ValueError('Excess input frames')
   finally:
    reader.stdout.close();mask_reader.stdout.close()
    for c in [writer,mask_writer]:
     with contextlib.suppress(OSError):c.stdin.close()
    codes=[c.wait() for c in [reader,mask_reader,writer,mask_writer]]
   if any(codes):raise ValueError('Composition failed')
  if yh.hexdigest()!=broad['y_sha256']:raise ValueError('Full source Y digest differs')
  status('verifying_compound_candidate')
  verified=hashlib.sha256();verifiedalpha=hashlib.sha256()
  with (out/'verify.log').open('w') as log:
   reader=d.decoder(output,'yuv444p',log);ar=d.decoder(alpha_path,'gray',log)
   try:
    for _ in range(broad['frames']):
     raw=d.read_exact(reader.stdout,P*3);a=d.read_exact(ar.stdout,P)
     if len(raw)!=P*3 or len(a)!=P:raise ValueError('Short encoded decode')
     verified.update(raw);verifiedalpha.update(a)
    if reader.stdout.read(1) or ar.stdout.read(1):raise ValueError('Excess encoded frames')
   finally:reader.stdout.close();ar.stdout.close();codes=[reader.wait(),ar.wait()]
   if any(codes):raise ValueError('Final decode failed')
  if verified.hexdigest()!=payload.hexdigest() or verifiedalpha.hexdigest()!=ah.hexdigest():raise ValueError('Encoded native payload differs')
  record=copy.deepcopy(broad)
  record.update(fingerprint=fingerprint,output=str(output),output_sha256=p.sha256(output),full_yuv_sha256=verified.hexdigest(),material_alpha=str(alpha_path),material_alpha_sha256=p.sha256(alpha_path),material_alpha_decoded_sha256=ah.hexdigest(),material_alpha_semantics='Binary spatial support of reviewed broad board and fourteen reviewed back deltas; not numerical blend weights.',compound_prior_receipt=str(broad_path),compound_prior_receipt_sha256=p.sha256(broad_path),compound_prior_output_sha256=broad['output_sha256'],bounded_back_trial=str(trial_path),bounded_back_trial_sha256=p.sha256(trial_path),bounded_back_visual_review=str(worker),bounded_back_visual_review_sha256=p.sha256(worker),exact_reviewed_back_payloads=True,exact_all_other_yuv_to_reviewed_broad=True,back_patch_yuv_sha256=patched.hexdigest(),all_other_yuv_sha256=unchanged.hexdigest(),quality_acceptance='compound_independent_preservation_review_pending',method='Reviewed broad physical-board UV correction plus exactly fourteen reviewed source-clear back-edge payloads; originalY and prior onset intact',finished_at=p.utc(),timing=d.verify_timestamps(output,broad['frames'],source),limitations=['Conservative blurred shoulder/hand/underarm guards remain outside these fourteen bounded comparisons.','No continuous-rim extrapolation or final playback acceptance.'])
  d.verify_video_geometry(output,source);p.atomic_json(receipt,record)
 status('compound_candidate_ready_pending_independent_QA',receipt=str(receipt),output_sha256=record['output_sha256'])
if __name__=='__main__':
 try:main()
 except BaseException as e:status('failed',error=str(e));raise
