"""Unselected same-frame source-UV comparison on reviewed soft coat contours."""
from pathlib import Path
import sys,subprocess,hashlib
import numpy as np
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
import production as p
import delivery as d
OUT=ROOT/'comparison_v01';OUT.mkdir(parents=True,exist_ok=True)
geometry_path=p.PROJECT/'scenes/qc/material_disposition_v1/coat_fringe_059176/source_contour_trial_v1/geometry_trial.json'
review_path=geometry_path.parent/'source_review.json'
assert p.sha256(geometry_path)=='a76f89103cdc0729032f9dee23b6ff28ef7d357aa3075b6865fb64224af11ed5'
assert p.sha256(review_path)=='e31177ac8180e0a2cb00909145e33b183641d87d6ede9828911e81e4595f2d20'
review=p.read_json(review_path);assert review['status']=='source_contour_local_comparison_trial_ready'
geometry=p.read_json(geometry_path);mapping={r['frame_global']:r for r in geometry['records']}
expected=set(range(59179,59207))|set(range(59236,59249))
assert set(mapping)==expected
choice=p.read_json(p.HERE/'source_y_overrides.json')['shot_059176'];base=p.read_json(choice['receipt'])
assert base['output_sha256']=='7a682bb2e7ec8c3ab3dd1e3807cbf4950f304bd738516a002cb94ca5edd40a59'
assert p.sha256(base['output'])==base['output_sha256']
cache=next(p.read_json(f) for f in (p.RENDER/'source_batches').glob('batch_05_*/source_mapping.json') if p.read_json(f)['source_clip_start_frame']==58480)
assert cache['status']=='complete' and p.sha256(cache['path'])==cache['sha256']
P=960*720
def rgb(raw):
    command=[str(p.FFMPEG),'-v','error','-f','rawvideo','-pix_fmt','yuv444p','-s','960x720','-color_range','tv','-colorspace','bt470bg','-i','pipe:0','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1']
    return Image.frombytes('RGB',(960,720),subprocess.run(command,input=raw,capture_output=True,check=True).stdout)
tiles=[];records=[]
with (OUT/'decode.log').open('w') as log:
    for start,end in [(59179,59207),(59236,59249)]:
        old_decoder=d.decoder(base['output'],'yuv444p',log,start-base['start_frame'],end-start)
        source_decoder=d.decoder(cache['path'],'yuv444p',log,start-cache['source_clip_start_frame'],end-start)
        try:
            for frame in range(start,end):
                old=np.frombuffer(d.read_exact(old_decoder.stdout,P*3),np.uint8).reshape(3,720,960)
                source=np.frombuffer(d.read_exact(source_decoder.stdout,P*3),np.uint8).reshape(3,720,960)
                row=mapping[frame];assert p.sha256(row['alpha_path'])==row['alpha_sha256']
                assert hashlib.sha256(source[0].tobytes()).hexdigest()==row['source_Y_sha256']
                assert np.array_equal(source[0],old[0])
                alpha=np.array(Image.open(row['alpha_path']).convert('L'));assert alpha.shape==(720,960)
                weight=alpha.astype(np.float32)/255.
                trial=old.copy();trial[1:]=np.rint(old[1:].astype(np.float32)*(1-weight)+source[1:].astype(np.float32)*weight).clip(0,255).astype(np.uint8)
                assert np.array_equal(trial[0],old[0]) and np.array_equal(trial[1:,alpha==0],old[1:,alpha==0])
                source_rgb,old_rgb,new_rgb=[rgb(v.tobytes()) for v in [source,old,trial]]
                path=OUT/f'trial_{frame:06d}.png';new_rgb.save(path)
                raw_path=OUT/f'trial_{frame:06d}.yuv';raw_path.write_bytes(trial.tobytes())
                ys,xs=np.nonzero(alpha)
                if len(xs):crop=(max(0,int(xs.min())-18),max(0,int(ys.min())-15),min(960,int(xs.max())+20),min(720,int(ys.max())+16))
                else:crop=(730,540,850,720)
                tile=Image.new('RGB',(900,280));ImageDraw.Draw(tile).text((5,5),f'G{frame}: original source | selected color | source-edge UV trial',fill='white')
                for j,img in enumerate([source_rgb,old_rgb,new_rgb]):tile.paste(img.crop(crop).resize((300,250)),(j*300,25))
                tiles.append(tile)
                records.append(dict(frame_global=frame,alpha_path=row['alpha_path'],alpha_sha256=row['alpha_sha256'],output=str(raw_path),output_sha256=p.sha256(raw_path),png=str(path),png_sha256=p.sha256(path),exact_original_Y=True,exact_UV_outside_alpha=True,changed_pixels=int(np.any(trial[1:]!=old[1:],axis=0).sum()),crop_xyxy=crop))
            assert not old_decoder.stdout.read(1) and not source_decoder.stdout.read(1)
        finally:
            old_decoder.stdout.close();source_decoder.stdout.close()
            assert old_decoder.wait()==0 and source_decoder.wait()==0
for start in range(0,len(tiles),4):
    sheet=Image.new('RGB',(1800,560))
    for k,tile in enumerate(tiles[start:start+4]):sheet.paste(tile,((k%2)*900,(k//2)*280))
    sheet.save(OUT/f'contact_{start//4:02d}.jpg',quality=95)
p.atomic_json(OUT/'trial.json',dict(schema_version=1,status='source_edge_UV_comparison_pending_actual_color_review',created_at=p.utc(),source_cache=cache['path'],source_cache_sha256=cache['sha256'],
    base_receipt=choice['receipt'],base_output_sha256=base['output_sha256'],geometry=str(geometry_path),geometry_sha256=p.sha256(geometry_path),source_review=str(review_path),source_review_sha256=p.sha256(review_path),records=records,
    operation='Blend only source-reviewed soft background edge fraction toward same-frame original UV. No Y modification, no source-mask mutation.',
    limitations=['41 diagnostic frames only; endpoints are not production patch boundaries.','G59178 and all other frames/media remain untouched.','Requires actual color review and expanded temporal extent before any candidate selection.'],selection_changed=False,delivery_acceptance=False))
print(str(OUT/'trial.json'))
