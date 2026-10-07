"""Trial incoming podium material before measured source dissolve, without changing source Y."""
from pathlib import Path
import sys,copy,hashlib
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
import production as p
import delivery as d
from prepare_comparison import apply,rgb,P
def main():
 out=ROOT/'entry_comparison_v01';out.mkdir(parents=True,exist_ok=True)
 method_review=p.PROJECT/'scenes/qc/material_disposition_v1/podium_material_comparison_v01/visual_review.json'
 assert p.sha256(method_review)=='545957e32ef4d9137691dc833d0397493b13b872bec2d9320a893eb09738000b'
 plan=p.read_json(p.HERE/'science_batch05_bridge/plan.json');job=next(j for j in plan['jobs'] if j['boundary_frame']==58480)
 entry=p.read_json(job['receipt']);context=entry['overlap_master']
 selected=p.read_json(p.read_json(p.HERE/'source_y_overrides.json')['shot_058480']['receipt'])
 gp=p.PROJECT/'scenes/qc/material_disposition_v1/podium_geometry_worker/shot_058480/geometry_proposal.json';g=p.read_json(gp)
 row=next(r for r in g['frames'] if r['frame_global']==58484)
 assert p.sha256(gp)=='25c5ddad28aea8f5147500ae71580ed8dad8a8f0f3ed21d8e3c029fde9b8c834'
 for path,sha in [(entry['base_output'],entry['base_output_sha256']),(context['output'],context['output_sha256']),(selected['output'],selected['output_sha256'])]:assert p.sha256(path)==sha
 coeff={r['frame_global']:r['alpha_incoming_for_review'] for r in entry['transition']['native_source_alpha']}
 records=[];tiles=[]
 with (out/'decode.log').open('w') as log:
  original=d.decoder(g['source_cache'],'yuv444p',log,0,5);incoming=d.decoder(entry['base_output'],'yuv444p',log,0,5)
  outgoing=d.decoder(context['output'],'yuv444p',log,58480-context['start_frame'],4);prior=d.decoder(selected['output'],'yuv444p',log,0,5)
  readers=[original,incoming,outgoing,prior]
  try:
   for frame in range(58480,58485):
    s=np.frombuffer(d.read_exact(original.stdout,P*3),np.uint8).reshape(3,720,960)
    inc=np.frombuffer(d.read_exact(incoming.stdout,P*3),np.uint8).reshape(3,720,960)
    old=np.frombuffer(d.read_exact(prior.stdout,P*3),np.uint8).reshape(3,720,960)
    assert np.array_equal(s[0],inc[0]) and np.array_equal(s[0],old[0])
    fixed,alpha=apply(inc,s,row)
    a=coeff.get(frame,1.0);trial=old.copy()
    if frame<58484:
     outgoing_field=np.frombuffer(d.read_exact(outgoing.stdout,P*3),np.uint8).reshape(3,720,960)
     reconstructed=np.rint(outgoing_field[1:].astype(np.float32)*(1-a)+inc[1:].astype(np.float32)*a).astype(np.uint8)
     assert np.array_equal(reconstructed,old[1:]),'Source-alpha reconstruction differs'
     trial[1:]=np.rint(outgoing_field[1:].astype(np.float32)*(1-a)+fixed[1:].astype(np.float32)*a).clip(0,255).astype(np.uint8)
    else:trial=fixed
    active=np.any(alpha>0,axis=0)
    assert np.array_equal(trial[0],old[0]) and np.array_equal(trial[1:,~active],old[1:,~active])
    path=out/f'trial_{frame:06d}.yuv';path.write_bytes(trial.tobytes());png=out/f'trial_{frame:06d}.png';new_rgb=rgb(trial.tobytes());new_rgb.save(png)
    hypothesis=rgb(inc.tobytes());overlay=hypothesis.copy();dr=ImageDraw.Draw(overlay)
    dr.line([tuple(v) for v in row['wood_plane_polygon_native']]+[tuple(row['wood_plane_polygon_native'][0])],fill=(255,0,255),width=2)
    dr.line([tuple(v) for v in row['printed_crest_contour_native']]+[tuple(row['printed_crest_contour_native'][0])],fill=(0,255,255),width=2)
    overlay.save(out/f'incoming_geometry_trial_{frame:06d}.png')
    tile=Image.new('RGB',(1440,385));ImageDraw.Draw(tile).text((4,4),f'G{frame}, incoming source alpha {a:.6f}: source | selected | corrected incoming-field trial',fill='white')
    for j,image in enumerate([rgb(s.tobytes()),rgb(old.tobytes()),new_rgb]):tile.paste(image.resize((480,360)),(j*480,25))
    tiles.append(tile);records.append(dict(frame_global=frame,incoming_alpha=a,source_Y_sha256=hashlib.sha256(s[0].tobytes()).hexdigest(),output=str(path),output_sha256=p.sha256(path),png=str(png),png_sha256=p.sha256(png),exact_source_Y=True,exact_UV_outside_incoming_material_contours=True))
   assert not any(r.stdout.read(1) for r in readers)
  finally:
   for r in readers:r.stdout.close()
   assert not any(r.wait() for r in readers)
 for start in [0,3]:
  sheet=Image.new('RGB',(1440,385*len(tiles[start:start+3])))
  for j,tile in enumerate(tiles[start:start+3]):sheet.paste(tile,(0,j*385))
  sheet.save(out/f'contact_{start//3:02d}.jpg',quality=95)
 p.atomic_json(out/'trial.json',dict(status='incoming_podium_hypothesis_trial_pending_native_review',created_at=p.utc(),records=records,incoming_geometry_source=str(gp),incoming_geometry_sha256=p.sha256(gp),incoming_geometry_frame=58484,hypothesis='First clear incoming stationary-camera source plane and printed-crest contours held only over four original dissolve frames; applied to incoming field BEFORE measured alpha. This is a source-specific trial requiring native review, not a canonical geometry extension.',entry_receipt=job['receipt'],entry_receipt_sha256=p.sha256(job['receipt']),prior_selected_output_sha256=selected['output_sha256'],incoming_output_sha256=entry['base_output_sha256'],outgoing_context_sha256=context['output_sha256'],source_alpha=entry['transition']['native_source_alpha'],delivery_acceptance=False,selection_changed=False))
 print(str(out/'trial.json'))
if __name__=='__main__':main()
