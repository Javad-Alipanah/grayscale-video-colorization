"""Bounded bidirectional source-only foreground trials; CUDA requires engine lock."""
import argparse,os,json,hashlib,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--plan',required=True);p.add_argument('--device',choices=['cpu','cuda'],default='cpu');p.add_argument('--limit-per-direction',type=int);p.add_argument('--engine-gpu-lock-held',action='store_true');a=p.parse_args()
if a.device=='cpu':os.environ['CUDA_VISIBLE_DEVICES']='-1'
elif not a.engine_gpu_lock_held:raise ValueError('CUDA requires the engine exclusive GPU lock')
os.environ['HF_HUB_DISABLE_PROGRESS_BARS']='1'
import torch,numpy as np,cv2
from PIL import Image
from transformers import Sam2VideoModel,Sam2VideoProcessor
from sample_native import BASE,H,W
torch.set_num_threads(4);torch.set_num_interop_threads(2);cv2.setNumThreads(1)
planpath=Path(a.plan).resolve();plan=json.load(open(planpath));assert plan['status']=='bounded_source_temporal_trial_prepared'
md=BASE/'projection_masks/cpu_sam2_trial/model'
model=Sam2VideoModel.from_pretrained(md,local_files_only=True,dtype=torch.float32).to(a.device).eval();processor=Sam2VideoProcessor.from_pretrained(md,local_files_only=True)
whole_start=time.monotonic();completed=[]
for job in plan['jobs']:
 gp=Path(job['geometry_path']);assert hashlib.sha256(gp.read_bytes()).hexdigest()==job['geometry_sha256'];geo=json.load(open(gp));gf={r['frame_global']:r for r in geo['frames']}
 anchor=Path(job['anchor_mask']);assert hashlib.sha256(anchor.read_bytes()).hexdigest()==job['anchor_sha256'];initial=np.array(Image.open(anchor))>0;assert initial.shape==(H,W)
 source=Path(job['source_gray']);assert source.stat().st_size==(geo['end_frame']-geo['start_frame'])*H*W
 with source.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==job['source_gray_sha256']
 y=np.memmap(source,dtype=np.uint8,mode='r',shape=(geo['end_frame']-geo['start_frame'],H,W))
 for direction in ['forward','backward']:
  frames=list(range(job['anchor_frame'],job['end_frame'])) if direction=='forward' else list(range(job['anchor_frame'],job['start_frame']-1,-1))
  if a.limit_per_direction:frames=frames[:a.limit_per_direction]
  out=Path(job['output_root'])/f'{a.device}_{direction}'
  if a.limit_per_direction:out=out.parent/(out.name+f'_smoke{a.limit_per_direction}')
  out.mkdir(parents=True,exist_ok=True)
  session=processor.init_video_session(inference_device=a.device,inference_state_device='cpu',processing_device='cpu',video_storage_device='cpu',dtype=torch.float32);session.video_height=H;session.video_width=W
  processor.add_inputs_to_inference_session(session,frame_idx=0,obj_ids=1,input_masks=initial)
  records=[];started=time.monotonic()
  for i,n in enumerate(frames):
   v=np.clip((y[n-geo['start_frame']].astype(float)-16)*255/219,0,255).astype(np.uint8);rgb=np.repeat(v[:,:,None],3,2);inputs=processor(images=Image.fromarray(rgb),return_tensors='pt')
   with torch.inference_mode():
    pred=model(session,frame_idx=i,frame=inputs['pixel_values'].to(a.device))
    mask=processor.post_process_masks([pred.pred_masks],original_sizes=inputs['original_sizes'],binarize=True)[0][0,0].cpu().numpy().astype(np.uint8)*255
   assert mask.shape==(H,W);target=out/f'person_{n:06d}.png';Image.fromarray(mask).save(target)
   screen=np.zeros((H,W),np.uint8);poly=gf[n]['screen_polygon_native']
   if poly:cv2.fillPoly(screen,[np.array(poly).round().astype(np.int32)],255)
   screen[mask>0]=0;sel=screen>0;rgb[sel]=(rgb[sel]*.7+np.array([0,200,255])*.3).astype(np.uint8);Image.fromarray(rgb).save(out/f'overlay_{n:06d}.png')
   records.append({'frame_global':n,'mask_path':str(target),'mask_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'foreground_pixels':int((mask>0).sum())})
   if i%20==0 or i==len(frames)-1:print(json.dumps({'scene':job['scene_id'],'direction':direction,'frame':n,'seconds':round(time.monotonic()-started,2)}),flush=True)
   for old in list(session.processed_frames):
    if old<i:session.processed_frames.pop(old,None)
  result={'schema_version':1,'status':'source_mask_temporal_trial_pending_review','scene_id':job['scene_id'],'device':a.device,'direction':direction,'frames':len(frames),'frame_global_order':frames,'seconds':time.monotonic()-started,'anchor_mask':str(anchor),'anchor_sha256':job['anchor_sha256'],'source_sha256':plan['source_sha256'],'source_gray':str(source),'source_gray_sha256':job['source_gray_sha256'],'geometry_path':str(gp),'geometry_sha256':job['geometry_sha256'],'plan':str(planpath),'plan_sha256':hashlib.sha256(planpath.read_bytes()).hexdigest(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'mask_semantics':'255=source-derived foreground lecturer,0=background; not scientific-screen replacement mask','records':records,'delivery_acceptance':False}
  rp=out/'trial.json';rp.write_text(json.dumps(result,indent=2));completed.append(str(rp))
print(json.dumps({'complete':True,'receipts':completed,'total_seconds':time.monotonic()-whole_start}),flush=True)
