"""Assemble exact reviewed half maps for an unselected combined-alpha trial."""
from pathlib import Path
import sys
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT.parent));import production as p
first=p.PROJECT/'scenes/qc/board_zoom_material_trial/dense_review/conservative_guard_sol_v2/candidate_map.json'
second=p.PROJECT/'reference_sol/actor_second_half_candidate_map_v3.json'
assert p.sha256(first)=='dc22a7344731684a8e2bc8d2fe83035acc18a0d1d14ad11c3d535917ac6aaa68'
assert p.sha256(second)=='e8e52769065860b0ecca18df47030134db8311b0a3b7b586f4bb1a9cb0470a33'
a=p.read_json(first);b=p.read_json(second);records=[]
source=ROOT/'foreground_temporal_v01/source_027193_028464.gray';source_hash='d0ce7b37221827f8aafdbea8e534c56cacbccb74873185595b779e1824ab227e'
assert p.sha256(source)==source_hash
Y=np.memmap(source,np.uint8,mode='r',shape=(1271,720,960))
for half,doc in [(1,a),(2,b)]:
 for row in doc['records']:
  g=row['frame_global'];path=row['reviewed_mask'] if half==1 else row['reviewed_mask_path'];digest=row['reviewed_mask_sha256']
  assert p.sha256(path)==digest
  src_digest=row['source_Y_sha256'] if half==1 else row['source_y_frame_sha256']
  import hashlib
  assert hashlib.sha256(Y[g-27193].tobytes()).hexdigest()==src_digest
  mask=np.array(Image.open(path).convert('L'));assert mask.shape==(720,960) and np.isin(mask,[0,255]).all()
  records.append(dict(frame_global=g,mask_path=path,mask_sha256=digest,source_Y_sha256=src_digest,half=half,issues=row.get('issues',[])))
assert [r['frame_global'] for r in records]==list(range(27193,28464))
out=ROOT/'combined_foreground_v01.json'
p.atomic_json(out,dict(status='combined_source_map_pending_independent_delta_and_effective_alpha_review',frames=records,source=str(source),source_sha256=source_hash,bound_half_maps=[dict(path=str(q),sha256=p.sha256(q)) for q in [first,second]],retained_second_half_holds=b['hold_ranges'],selection_changed=False,delivery_acceptance=False,created_at=p.utc()))
print(str(out),p.sha256(out))
