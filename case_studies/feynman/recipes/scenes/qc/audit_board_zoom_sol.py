import json,hashlib,subprocess
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt
from sample_native import BASE,FF,W,H
from audit_dissolve_correction import sha
folder=Path('work/lecture1-color/render/delivery/material_trials/shot_026165/board_zoom_3d7b93fc699e8b89');tp=folder/'treatment.json';t=json.loads(tp.read_text());N=W*H
for pk,hk in [('output','output_sha256'),('material_prior_output','material_prior_output_sha256'),('material_alpha','material_alpha_sha256'),('crest_alpha','crest_alpha_sha256'),('foreground_map','foreground_map_sha256')]:assert sha(t[pk])==t[hk]
def pipe(path,pix):return subprocess.Popen([str(FF),'-v','error','-xerror','-threads','2','-i',str(path),'-an','-pix_fmt',pix,'-fps_mode','passthrough','-f','rawvideo','-'],stdout=subprocess.PIPE)
def read(p,n):
 b=bytearray()
 while len(b)<n:
  z=p.stdout.read(n-len(b))
  if not z:break
  b.extend(z)
 return bytes(b)
c=pipe(t['output'],'yuv444p');p=pipe(t['material_prior_output'],'yuv444p');a=pipe(t['material_alpha'],'gray');cr=pipe(t['crest_alpha'],'gray')
fg={r['frame_global']:r for r in json.loads(Path(t['foreground_map']).read_text())['frames']};yh=hashlib.sha256();ah=hashlib.sha256();zero=[];changed=[];crestframes=[]
for i in range(2299):
 g=26165+i;cb=read(c,N*3);pb=read(p,N*3);ab=read(a,N);assert len(cb)==len(pb)==N*3 and len(ab)==N
 ca=np.frombuffer(cb,np.uint8).reshape(3,H,W);pa=np.frombuffer(pb,np.uint8).reshape(3,H,W);al=np.frombuffer(ab,np.uint8).reshape(H,W);yh.update(cb[:N]);ah.update(ab);assert cb[:N]==pb[:N]
 delta=np.any(ca[1:]!=pa[1:],axis=0);assert not np.any(delta&(al==0)),g
 if not al.any():assert cb==pb;zero.append(g)
 if delta.any():changed.append(g)
 if g<26171:assert cb==pb
 if g in fg:
  r=fg[g];assert sha(r['mask_path'])==r['mask_sha256'];assert hashlib.sha256(cb[:N]).hexdigest()==r['source_Y_sha256']
  m=np.array(Image.open(r['mask_path']).convert('L'))>0;guard=distance_transform_edt(~m)<=8;assert not np.any(al[guard]);assert not np.any(delta[guard])
 if 27055<=g<27225:
  q=read(cr,N);assert len(q)==N;cm=np.frombuffer(q,np.uint8).reshape(H,W)>0;assert not np.any(al[cm]);assert np.array_equal(ca[1:,cm],pa[1:,cm]);crestframes.append(g)
 if i%300==0:print('verified',i,flush=True)
for proc in [c,p,a,cr]:assert not read(proc,1) and proc.wait()==0
expected=json.loads((BASE/'source_batch_02_per_shot_y.json').read_text())['shots']['shot_026165']['Y_sha256'];assert yh.hexdigest()==expected
assert ah.hexdigest()==t['material_alpha_decoded_sha256']
out=BASE/'board_zoom_material_trial/whole_candidate_integrity_sol.json';out.write_text(json.dumps({'status':'independent_whole2299_native_preservation_pass','treatment':str(tp.resolve()),'treatment_sha256':sha(tp),'output_sha256':t['output_sha256'],'frames':2299,'original_Y_sha256':yh.hexdigest(),'all_original_Y_exact':True,'all_UV_outside_exact_material_alpha_unchanged':True,'all1271_actor_core_plus_euclidean8pxguard_alpha_and_UV_unchanged':True,'first_six_onset_YUV_exact_to_prior':True,'all170_crest_spatial_alpha_UV_exact_to_prior':True,'crest_preservation_scope':'Only crest spatial-alpha pixels; entire170frame equality is not claimed.','zero_material_frames':zero,'changed_frames':changed,'actual_color_review_pending':True,'selection_allowed':False,'created_at':datetime.now(timezone.utc).isoformat()},indent=2));print(out,sha(out),flush=True)
