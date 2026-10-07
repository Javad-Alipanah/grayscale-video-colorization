"""Source-reviewed viewport exceptions; no media or current selection mutation."""
from pathlib import Path
import sys, copy
import numpy as np
from PIL import Image, ImageDraw
B=Path(__file__).resolve().parent
sys.path.insert(0,str(B.parent.parent));import production as p
prior=B/'source_viewport_v06/geometry_proposal.json'
assert p.sha256(prior)=='147eefac8ec08541fe7f9ce9a67a53c4e2ba83d61280e6918c21f364f9368f27'
doc=p.read_json(prior);Y=np.memmap(doc['source_cache'],np.uint8,mode='r',shape=(1271,720,960))
out=B/'source_edges_v07';out.mkdir(exist_ok=True)
# Native right-edge strip28010..33 shows the pale rail leaving the viewport.
# Conservative source-side limits keep its last visible pixels untouched,
# then release the inset gradually only after the rail has left the picture.
limits=dict(zip(range(28020,28029),[921,928,934,939,943,948,953,958,960]))
tiles=[];records=[]
for row in doc['frames']:
 g=row['frame_global']
 if g not in limits:continue
 old=copy.deepcopy(row['screen_polygons_native']);limit=limits[g]
 for poly in row['screen_polygons_native']:
  for pt in poly:pt[0]=min(pt[0],float(limit))
 row['source_native_exception']=dict(right_limit=limit,evidence=str(B/'source_viewport_v06/right_028010_028034.jpg'),policy='Source-observed pale rail excluded, then conservative viewport inset released over four clear frames.')
 src=Image.fromarray(np.clip(np.rint((Y[g-27193].astype(float)-16)*255/219),0,255).astype(np.uint8)).convert('RGB')
 for poly in row['screen_polygons_native']:ImageDraw.Draw(src).line([tuple(v) for v in poly]+[tuple(poly[0])],fill='yellow',width=2)
 png=out/f'overlay_{g:06d}.png';src.save(png)
 tile=Image.new('RGB',(480,382));tile.paste(src.resize((480,360)),(0,22));ImageDraw.Draw(tile).text((4,3),f'G{g} right source-plane limit {limit}',fill='white');tiles.append(tile)
 records.append(dict(frame_global=g,right_limit=limit,overlay=str(png),overlay_sha256=p.sha256(png),prior_polygons=old))
sheet=Image.new('RGB',(1440,1146))
for j,t in enumerate(tiles):sheet.paste(t,(j%3*480,j//3*382))
sheet.save(out/'contact.jpg',quality=96)
doc.update(status='source_edges_v07_pending_independent_trial_review',parent_proposal=str(prior),parent_proposal_sha256=p.sha256(prior),source_native_edge_exceptions=records,implementation_sha256=p.sha256(__file__),reviewed=False)
p.atomic_json(out/'geometry_proposal.json',doc)
p.atomic_json(out/'engine_source_review.json',dict(status='engine_source_geometry_scoped_pass_for_unselected_color_trial',geometry=str(out/'geometry_proposal.json'),geometry_sha256=p.sha256(out/'geometry_proposal.json'),source_sha256=p.sha256(doc['source_cache']),inherited_v05_review=str(B/'source_direct_v05/engine_source_review.json'),inherited_v05_review_sha256=p.sha256(B/'source_direct_v05/engine_source_review.json'),v06_all107_viewport_frames_inspected=True,v06_contact_hashes=[dict(path=str(q),sha256=p.sha256(q)) for q in sorted((B/'source_viewport_v06').glob('contact_*.jpg'))],native_detail_frames=[27541,28021,28225],rail_exit_source_strip=str(B/'source_viewport_v06/right_028010_028034.jpg'),rail_exit_source_strip_sha256=p.sha256(B/'source_viewport_v06/right_028010_028034.jpg'),bounded_exception_frames=list(limits),limitations=['Physical source geometry only; actor guards and actual temporal color still require review.','Source-inset pale frames, lower rails, curtain and podium retained.'],selection_changed=False,created_at=p.utc()))
print(p.sha256(out/'geometry_proposal.json'))
