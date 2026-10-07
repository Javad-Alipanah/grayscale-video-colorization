"""Unselected native podium wood/printed-crest comparison from reviewed source planes."""
from pathlib import Path
import hashlib,subprocess,sys
import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageOps
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
import production as p
import delivery as d
P=960*720
cv2.setNumThreads(2)
REVIEW=p.PROJECT/'scenes/qc/material_disposition_v1/podium_source_geometry_review.json'
EXPECTED_REVIEW='50d3d7eb0260e1fee435cc079468db60b96d2fa4e4621dc8dcbf3f6cb8948f3d'
SCOPES={
 'shot_058480':('25c5ddad28aea8f5147500ae71580ed8dad8a8f0f3ed21d8e3c029fde9b8c834',[58483,58484,58510,58550,58590,58600,58603,58604]),
 'shot_059176':('f8bb962d0be04a0e00db156b07b5d546e4c080eb3b051ca8192c26610089cd21',[59423,59424,59440,59480,59530,59560,59571,59572]),
}
def smooth(a):
 a=np.clip(a,0,1);return a*a*(3-2*a)
def polygon(points):
 image=Image.new('L',(960,720));ImageDraw.Draw(image).polygon([tuple(x) for x in points],fill=255)
 return np.array(image)>0
def alphas(row):
 if not row.get('application_allowed_for_independent_trial'):return np.zeros((2,720,960),np.uint8)
 wood=polygon(row['wood_plane_polygon_native']);crest=polygon(row['printed_crest_contour_native'])&wood
 for points in row['foreground_exclusion_polygons_native']:
  wood[polygon(points)]=False;crest[polygon(points)]=False
 # Keep the reviewed contour and every outer source boundary fixed.
 wood[cv2.dilate(crest.astype(np.uint8),np.ones((3,3),np.uint8))>0]=False
 weights=[]
 for mask,width in [(wood,3),(crest,2)]:
  weights.append(np.rint(255*smooth((cv2.distanceTransform(mask.astype(np.uint8),cv2.DIST_L2,5)-.5)/width)).astype(np.uint8))
 return np.stack(weights)
def apply(before,source,row):
 alpha=alphas(row);w=alpha.astype(np.float32)/255
 # Target measured from the already reviewed same-lecture G26837 wooden podium.
 # A modest source-Y shading dependence matches its brighter and darker samples.
 t=np.clip((source[0].astype(np.float32)-141)/55,0,1)
 wood_target=np.stack([104-5*t,148+3*t])
 out=before.copy();out[1:]=np.rint(before[1:].astype(np.float32)*(1-w[0])+wood_target*w[0]).clip(0,255).astype(np.uint8)
 out[1:]=np.rint(out[1:].astype(np.float32)*(1-w[1])+source[1:].astype(np.float32)*w[1]).clip(0,255).astype(np.uint8)
 assert np.array_equal(out[0],source[0]) and np.array_equal(out[1:,(alpha==0).all(axis=0)],before[1:,(alpha==0).all(axis=0)])
 return out,alpha
def rgb(raw):
 args=[str(p.FFMPEG),'-v','error','-f','rawvideo','-pix_fmt','yuv444p','-s','960x720','-color_range','tv','-colorspace','bt470bg','-i','pipe:0','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1']
 return Image.frombytes('RGB',(960,720),subprocess.run(args,input=raw,capture_output=True,check=True).stdout)
def main():
 assert p.sha256(REVIEW)==EXPECTED_REVIEW
 selected=p.read_json(p.HERE/'source_y_overrides.json')
 for shot,(expected,frames) in SCOPES.items():
  gp=p.PROJECT/'scenes/qc/material_disposition_v1/podium_geometry_worker'/shot/'geometry_proposal.json'
  assert p.sha256(gp)==expected;g=p.read_json(gp);rows={r['frame_global']:r for r in g['frames']}
  base=p.read_json(selected[shot]['receipt']);assert p.sha256(base['output'])==base['output_sha256']
  outdir=ROOT/'comparison_v01'/shot;outdir.mkdir(parents=True,exist_ok=True);records=[];tiles=[]
  assert p.sha256(g['source_cache'])==g['source_cache_sha256']
  with (outdir/'decode.log').open('w') as log:
   old=d.decoder(base['output'],'yuv444p',log,min(frames)-base['start_frame'],max(frames)-min(frames)+1)
   original=d.decoder(g['source_cache'],'yuv444p',log,min(frames)-g['source_frame_mapping'],max(frames)-min(frames)+1)
   try:
    for frame in range(min(frames),max(frames)+1):
     b=np.frombuffer(d.read_exact(old.stdout,P*3),np.uint8).reshape(3,720,960)
     s=np.frombuffer(d.read_exact(original.stdout,P*3),np.uint8).reshape(3,720,960)
     assert np.array_equal(b[0],s[0])
     if frame not in frames:continue
     row=rows.get(frame,{});trial,alpha=apply(b,s,row)
     source_rgb,before_rgb,after_rgb=[rgb(v.tobytes()) for v in [s,b,trial]]
     raw=outdir/f'trial_{frame:06d}.yuv';raw.write_bytes(trial.tobytes())
     png=outdir/f'trial_{frame:06d}.png';after_rgb.save(png)
     ap=[]
     for n,label in enumerate(['wood','crest']):
      path=outdir/f'{label}_alpha_{frame:06d}.png';Image.fromarray(alpha[n]).save(path);ap.append(dict(path=str(path),sha256=p.sha256(path)))
     crop=(480,350,960,720) if shot=='shot_058480' else (560,340,960,720)
     tile=Image.new('RGB',(1440,395));ImageDraw.Draw(tile).text((4,4),f'G{frame}: source | selected | existing-palette wood + source-neutral crest',fill='white')
     for n,img in enumerate([source_rgb,before_rgb,after_rgb]):
      part=ImageOps.contain(img.crop(crop),(480,370));tile.paste(part,(n*480+(480-part.width)//2,25))
     tiles.append(tile)
     records.append(dict(frame_global=frame,source_Y_sha256=hashlib.sha256(s[0].tobytes()).hexdigest(),output=str(raw),output_sha256=p.sha256(raw),png=str(png),png_sha256=p.sha256(png),alpha=ap,exact_original_Y=True,exact_UV_outside_alpha=True,application_allowed=bool(row.get('application_allowed_for_independent_trial'))))
    assert not old.stdout.read(1) and not original.stdout.read(1)
   finally:
    old.stdout.close();original.stdout.close();assert old.wait()==0 and original.wait()==0
  for start in range(0,len(tiles),4):
   sheet=Image.new('RGB',(1440,1580))
   for n,tile in enumerate(tiles[start:start+4]):sheet.paste(tile,(0,n*395))
   sheet.save(outdir/f'contact_{start//4:02d}.jpg',quality=95)
  p.atomic_json(outdir/'trial.json',dict(status='unselected_podium_material_method_trial',created_at=p.utc(),shot_id=shot,geometry=str(gp),geometry_sha256=expected,source_review=str(REVIEW),source_review_sha256=EXPECTED_REVIEW,base_receipt=selected[shot]['receipt'],base_output_sha256=base['output_sha256'],source_cache=g['source_cache'],source_cache_sha256=g['source_cache_sha256'],records=records,palette_measurements=str(ROOT/'existing_palette_measurements.json'),limits=['Stills only; actual dense temporal review required.','Incoming source mixtures are deliberately held, so continuity remains pending.','Conservative source-inset edges are unchanged, not invented.'],selection_changed=False,delivery_acceptance=False))
  print(str(outdir/'trial.json'),flush=True)
if __name__=='__main__':main()
