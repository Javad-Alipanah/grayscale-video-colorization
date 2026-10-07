"""Measure native UV in visually checked wood-only regions of existing media."""
from pathlib import Path
import sys
import numpy as np
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
import production as p
import delivery as d

ROOT.mkdir(parents=True,exist_ok=True)
receipt_path=p.resolve(p.read_json(p.HERE/'source_y_overrides.json')['shot_026165']['receipt'])
receipt=p.read_json(receipt_path)
assert receipt['output_sha256']=='8dc96dbf752c82b97bbd9abc7a2f939d25a87824745c69e97520f97fd82b92dc'
assert p.sha256(receipt['output'])==receipt['output_sha256']
frame=26837
with (ROOT/'reference_decode.log').open('w') as log:
    child=d.decoder(receipt['output'],'yuv444p',log,frame-receipt['start_frame'],1)
    raw=d.read_exact(child.stdout,960*720*3)
    assert len(raw)==960*720*3 and not child.stdout.read(1)
    child.stdout.close(); assert child.wait()==0
planes=np.frombuffer(raw,np.uint8).reshape(3,720,960)
regions=[('upper_lit_wood',[745,390,920,440]),
         ('left_lower_wood',[703,555,728,650]),
         ('right_lower_wood',[944,505,953,645])]
measurements=[]
preview=p.PROJECT/'scenes/qc/podium_v02_review_worker/global_026837.png'
image=Image.open(preview).convert('RGB');draw=ImageDraw.Draw(image)
for name,(x0,y0,x1,y1) in regions:
    pixels=planes[:,y0:y1,x0:x1]
    measurements.append(dict(name=name,roi_xyxy=[x0,y0,x1,y1],pixels=int(pixels.shape[1]*pixels.shape[2]),
        median_yuv=np.median(pixels,axis=(1,2)).tolist(),
        uv_percentiles={str(q):np.percentile(pixels[1:],q,axis=(1,2)).tolist() for q in [10,25,50,75,90]}))
    draw.rectangle((x0,y0,x1,y1),outline='magenta',width=2)
image.save(ROOT/'existing_podium_reference_regions.png')
record=dict(status='existing_native_palette_measurement_only',created_at=p.utc(),frame_global=frame,
    reference_receipt=str(receipt_path),reference_receipt_sha256=p.sha256(receipt_path),
    reference_output=receipt['output'],reference_output_sha256=receipt['output_sha256'],
    measurements=measurements,
    method='Native limited-range YUV444 planes from the locally reviewed same physical podium; wood-only regions chosen from actual native image. No RGB-derived target.',
    scope='Palette evidence for bounded unselected still trials once source geometry is reviewed. Brightness and shading must remain original Y; printed crest and actors are excluded from material regions.',
    limitations=['The selected regions have different source illumination; a single target is not a recovered historical color.',
        'This measurement does not approve any temporal/spatial material mask or change any output.'],
    selection_changed=False,delivery_acceptance=False)
p.atomic_json(ROOT/'existing_palette_measurements.json',record)
print(record['measurements'])
