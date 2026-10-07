"""Versioned viewport correction for weak false edges whose surveyed edge is offscreen."""
from pathlib import Path
import sys,copy
import numpy as np
from PIL import Image,ImageDraw
B=Path(__file__).resolve().parent;sys.path.insert(0,str(B.parent.parent));import production as p
prior=B/'source_direct_v05/geometry_proposal.json';doc=p.read_json(prior)
assert p.sha256(prior)=='3c6505c77b96ef4788788d02361a5312fae8d721ffee531eebd02e695e0cc1cf'
Y=np.memmap(doc['source_cache'],np.uint8,mode='r',shape=(1271,720,960))
OUT=B/'source_viewport_v06';OUT.mkdir(exist_ok=True)
changed=[];tiles=[]
for row in doc['frames']:
 old=copy.deepcopy(row['screen_polygons_native']);polys=row['screen_polygons_native'];sides=[]
 if not polys:continue
 for side,indices in [('left',[0,2]),('right',[1,3])]:
  edges=[row['source_plane_edges'][i] for i in indices]
  off=any(e.get('weak_edge_conservative_inset') and (e['predicted']<=0 if side=='left' else e['predicted']>=960) and e.get('score',0)<0 for e in edges)
  if not off:continue
  allowed=any(a==0 if side=='left' else b==960 for a,b in row['source_allowed_upper_intervals'])
  if not allowed:continue
  poly=min(polys,key=lambda v:min(x[0] for x in v)) if side=='left' else max(polys,key=lambda v:max(x[0] for x in v))
  extreme=min(v[0] for v in poly) if side=='left' else max(v[0] for v in poly)
  near=[v for v in poly if abs(v[0]-extreme)<20]
  # Preserve the source lower-rail slope rather than stretching its vertical extent.
  bottom=sorted(poly,key=lambda v:v[1],reverse=True)[:2]
  slope=(bottom[1][1]-bottom[0][1])/(bottom[1][0]-bottom[0][0]) if abs(bottom[1][0]-bottom[0][0])>1 else 0
  for v in near:
   target=0.0 if side=='left' else 960.0
   if v[1]>100:v[1]=min(720.,max(0.,v[1]+slope*(target-v[0])))
   v[0]=target
  sides.append(side)
 if not sides:continue
 g=row['frame_global'];row['viewport_extension']=dict(sides=sides,policy='Only negative-score weak edge whose source-survey prior is outside viewport, with no structural exclusion at that viewport side. Source native review required.')
 changed.append(g)
 src=Image.fromarray(np.clip(np.rint((Y[g-27193].astype(float)-16)*255/219),0,255).astype(np.uint8)).convert('RGB')
 oldmask=Image.new('L',(960,720));newmask=Image.new('L',(960,720))
 for mask,pp in [(oldmask,old),(newmask,polys)]:
  dr=ImageDraw.Draw(mask)
  for poly in pp:dr.polygon([tuple(v) for v in poly],fill=255)
  for obj in row['source_object_exclusions']:dr.polygon([tuple(v) for v in obj['polygon_native']],fill=0)
 delta=np.array(newmask)>np.array(oldmask)
 over=Image.composite(Image.blend(src,Image.new('RGB',(960,720),(0,170,255)),.3),src,Image.fromarray((delta*255).astype(np.uint8)))
 for poly in polys:ImageDraw.Draw(over).line([tuple(v) for v in poly]+[tuple(poly[0])],fill='yellow',width=2)
 path=OUT/f'overlay_{g:06d}.png';over.save(path)
 tile=Image.new('RGB',(480,382));tile.paste(over.resize((480,360)),(0,22));ImageDraw.Draw(tile).text((5,3),f'G{g} cyan=new viewport area; source only',fill='white');tiles.append((g,tile))
contacts=[]
for off in range(0,len(tiles),9):
 group=tiles[off:off+9];sheet=Image.new('RGB',(1440,382*((len(group)+2)//3)))
 for j,(_,tile) in enumerate(group):sheet.paste(tile,(j%3*480,j//3*382))
 path=OUT/f'contact_{off//9:02d}.jpg';sheet.save(path,quality=95);contacts.append(dict(path=str(path),sha256=p.sha256(path),frames=[g for g,_ in group]))
doc.update(status='source_viewport_extension_trial_pending_native_review',parent_proposal=str(prior),parent_proposal_sha256=p.sha256(prior),changed_viewport_frames=changed,viewport_contacts=contacts,implementation_sha256=p.sha256(__file__),reviewed=False)
p.atomic_json(OUT/'geometry_proposal.json',doc)
print(len(changed),len(contacts),p.sha256(OUT/'geometry_proposal.json'))
