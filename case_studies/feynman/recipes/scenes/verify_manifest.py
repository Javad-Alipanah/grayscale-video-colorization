from pathlib import Path
import subprocess,json,hashlib,datetime
import numpy as np
from PIL import Image
p=Path(__file__).parent;root=p.parents[2];ff=root/'work/download-tools/ffmpeg.exe';m=json.loads((p/'manifest.json').read_text());first=json.loads((p/'first_batch_manifest.json').read_text())
shots=m['shots'];pts=np.array(json.loads((p/'source_pts.json').read_text())['source_pts'],dtype=np.int64)
assert len(pts)==m['source']['frame_count']==80026
assert shots[0]['start_frame']==0 and shots[-1]['end_frame']==len(pts)
assert all(a['end_frame']==b['start_frame'] for a,b in zip(shots,shots[1:]))
assert sum(s['frames'] for s in shots)==len(pts)
assert shots[:len(first['shots'])]==first['shots'],'Frozen batch1 shot metadata changed'
assert np.all(np.diff(pts)>0)
delta,counts=np.unique(np.diff(pts),return_counts=True)
nominal=np.arange(len(pts))*1001/24
deviation=pts-nominal
candidate_count=0
for s in shots:
    assert s['frames']==s['end_frame']-s['start_frame']
    for r in s['reference_candidates']:
        path=Path(r['source_path']);assert path.exists();assert s['start_frame']<=r['frame_global']<s['end_frame']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==r['sha256'];assert Image.open(path).size==(960,720);candidate_count+=1
mapping_path=root/'work/lecture1-color/render/source_batches/batch_01_866cdc46cc4f/source_mapping.json'
clip=mapping_path.parent/'source_ffv1.mkv';assert clip.exists()
ids=sorted(set([0,1,15015,15016]+[j for s in first['shots'] for j in [max(0,s['start_frame']-1),s['start_frame'],min(15016,s['start_frame']+1)]]))
def balanced(items):
    if len(items)==1:return f'eq(n\\,{items[0]})'
    mid=len(items)//2
    return '('+balanced(items[:mid])+'+'+balanced(items[mid:])+')'
def rawframes(path):
    proc=subprocess.run([str(ff),'-hide_banner','-loglevel','error','-i',str(path),'-vf','select='+balanced(ids)+',extractplanes=y','-frames:v',str(len(ids)),'-fps_mode','passthrough','-pix_fmt','gray','-f','rawvideo','pipe:1'],capture_output=True,check=True)
    assert len(proc.stdout)==len(ids)*960*720
    return proc.stdout
source=rawframes(m['source']['path']);cached=rawframes(clip);assert source==cached,'Sampled Y differs from original source'
report={'schema_version':1,'status':'passed','verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_frames':len(pts),'manifest_shots':len(shots),'contiguous_half_open_frame_coverage':True,'sum_frames':sum(s['frames'] for s in shots),'native_candidate_hashes_and_dimensions_verified':candidate_count,'frozen_first_batch_shots_unchanged':True,'source_pts_strictly_increasing':True,'source_pts_delta_ms':dict(zip(map(str,delta.tolist()),counts.tolist())),'source_pts_error_vs_nominal_ms':{'min':float(deviation.min()),'max':float(deviation.max())},'batch_01_source_clip':str(clip),'batch_01_mapping_path':str(mapping_path),'batch_01_sampled_y_frame_ids':ids,'sample_y_frames':len(ids),'sample_y_bytes':len(source),'source_sample_y_sha256':hashlib.sha256(source).hexdigest(),'cache_sample_y_sha256':hashlib.sha256(cached).hexdigest(),'sample_y_exact_match':True,'full_delivery_y_digest':'Required during master assembly; this verification samples batch1 boundaries only.','native_reference_visual_review':'All249selected native candidates inspected in 11contact sheets; original motion blur/ghosting retained.','fullcut_visual_review':'Full lecture overview10seconds plus136primarycandidate rows,9lagcandidate rows and targetedpan/dissolveonset strips inspected.'}
(p/'verification.json').write_text(json.dumps(report,indent=2))
m['source']['sha256']='37937a5485485f69edd209a84fde0f5522d1db085b540f2ff16b8a7aeceb1033'
m['verification_path']=str(p/'verification.json');m['batches'][0].update(source_clip_path=str(clip),source_clip_start_frame=0,source_clip_end_frame=15017,source_mapping_path=str(mapping_path))
m['review']['native_reference_candidates_visually_reviewed']=249
(p/'manifest.json').write_text(json.dumps(m,indent=2))
print(json.dumps({k:report[k] for k in ['status','source_frames','manifest_shots','native_candidate_hashes_and_dimensions_verified','sample_y_frames','sample_y_exact_match','source_pts_delta_ms','source_pts_error_vs_nominal_ms']}))
