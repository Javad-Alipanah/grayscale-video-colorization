"""Native and dense overview evidence for the closed, unselected board trial."""
from pathlib import Path
import sys,argparse,hashlib
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT.parent));import production as p;import delivery as d
P=960*720
def main(receipt):
 row=p.read_json(receipt);assert row['full_decode_verified'] and p.sha256(row['output'])==row['output_sha256']
 out=Path(receipt).parent/'native_review';out.mkdir(exist_ok=True)
 mp=p.read_json(row['foreground_map']);mapping={r['frame_global']:r for r in mp['frames']}
 first=p.read_json(p.PROJECT/'scenes/qc/board_zoom_material_trial/dense_review/conservative_guard_sol_v2/candidate_map.json')
 second=p.read_json(p.PROJECT/'reference_sol/actor_second_half_candidate_map_v3.json')
 probes=set(first['changed_frames'])|{g for r in second['hold_ranges'] for g in range(*r['range_half_open'])}|set(range(27193,28464,48))|{27193,27194,27217,27225,27345,27417,27430,27517,27959,27960,28020,28021,28022,28028,28225,28453,28454,28462,28463}
 start,end=27185,28464;overview=[];pairs=[];ov_contacts=[];pair_contacts=[];records=[]
 with (out/'decode.log').open('w') as log:
  readers=[d.decoder(row['material_prior_output'],'rgb24',log,start-row['start_frame'],end-start),d.decoder(row['output'],'rgb24',log,start-row['start_frame'],end-start)]
  try:
   for g in range(start,end):
    raw=[d.read_exact(r.stdout,P*3) for r in readers];assert all(len(v)==P*3 for v in raw)
    prior,candidate=[Image.frombytes('RGB',(960,720),v) for v in raw]
    tile=Image.new('RGB',(480,382));tile.paste(candidate.resize((480,360)),(0,22));ImageDraw.Draw(tile).text((4,3),f'G{g} unselected source-Y board trial',fill='white');overview.append((g,tile))
    if len(overview)==12 or g==end-1:
     sheet=Image.new('RGB',(1440,382*((len(overview)+2)//3)))
     for j,(_,t) in enumerate(overview):sheet.paste(t,(j%3*480,j//3*382))
     path=out/f'overview_{len(ov_contacts):03d}.jpg';sheet.save(path,quality=95);ov_contacts.append(dict(path=str(path),sha256=p.sha256(path),frames=[n for n,_ in overview]));overview=[]
    if g in probes or g<27193:
     path=out/f'candidate_{g:06d}.png';candidate.save(path)
     old=out/f'prior_{g:06d}.png';prior.save(old)
     actor=np.array(Image.open(mapping[g]['mask_path']).convert('L')) if g in mapping else np.zeros((720,960),np.uint8)
     ys,xs=np.nonzero(actor)
     x=max(0,min(480,int(np.median(xs))-240)) if len(xs) else 240
     crop=(x,300,x+480,720);piece=Image.new('RGB',(960,445));piece.paste(prior.crop(crop),(0,25));piece.paste(candidate.crop(crop),(480,25));ImageDraw.Draw(piece).text((4,4),f'G{g} prior | candidate; native1:1 crop {crop}',fill='white');pairs.append((g,piece))
     records.append(dict(frame_global=g,candidate=str(path),candidate_sha256=p.sha256(path),prior=str(old),prior_sha256=p.sha256(old),native_crop_xyxy=crop))
     if len(pairs)==4 or g==end-1:
      sheet=Image.new('RGB',(960,445*len(pairs)))
      for j,(_,t) in enumerate(pairs):sheet.paste(t,(0,j*445))
      cp=out/f'actor_pairs_{len(pair_contacts):03d}.jpg';sheet.save(cp,quality=96);pair_contacts.append(dict(path=str(cp),sha256=p.sha256(cp),frames=[n for n,_ in pairs]));pairs=[]
   assert all(not r.stdout.read(1) for r in readers)
  finally:
   for r in readers:r.stdout.close()
   assert all(r.wait()==0 for r in readers)
 p.atomic_json(out/'sampling.json',dict(status='closed_native_review_evidence_pending_visual_review',receipt=str(receipt),receipt_sha256=p.sha256(receipt),output_sha256=row['output_sha256'],scope=[start,end],overview_contacts=ov_contacts,native_pairs=pair_contacts,native_records=records,selection_changed=False,delivery_acceptance=False))
 print(str(out/'sampling.json'))
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--receipt',type=Path,required=True);main(ap.parse_args().receipt)
