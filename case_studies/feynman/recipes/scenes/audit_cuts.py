from pathlib import Path
import numpy as np,json
from scipy.ndimage import median_filter,maximum_filter1d
from PIL import Image,ImageDraw,ImageFont
p=Path(__file__).parent
s=np.load(p/'cut_scores.npz');mad=s['mad'];edge=s['edge'];hist=s['histogram_l1'];n=len(mad)
pts=json.loads((p/'source_pts.json').read_text())['source_pts']
a=np.memmap(p/'census_gray_160x120.raw',dtype=np.uint8,mode='r',shape=(n,120,160))
ratio=mad/(1+median_filter(mad,size=49))
measure=np.maximum(ratio/3,np.maximum(mad/28,hist/.28))
pool=np.where((measure>=1)&(measure==maximum_filter1d(measure,size=17)))[0]
# Force known accepted-pilot transition candidates, validating alignment here.
pool=sorted(set(pool.tolist()+[21579+x for x in [317,655,1228,1665,2956,3490]]))
recs=[{'frame':int(i),'pts_seconds':pts[i]/1000,'mad':float(mad[i]),'edge':float(edge[i]),'hist':float(hist[i]),'ratio':float(ratio[i])} for i in pool]
(p/'audit_candidates.json').write_text(json.dumps(recs,indent=2))
font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',17)
(p/'audit').mkdir(exist_ok=True)
for k in range(0,len(pool),8):
    ids=pool[k:k+8];b=Image.new('RGB',(1280,len(ids)*264),'#151515');d=ImageDraw.Draw(b)
    for r,i in enumerate(ids):
        for c,delta in enumerate([-5,-1,1,6]):
            j=max(0,min(n-1,i+delta));x=c*320;y=r*264;t=pts[j]/1000
            b.paste(Image.fromarray(a[j]).resize((320,240)),(x,y+24))
            d.text((x+3,y+2),f'{j} {int(t)//60}:{t%60:05.2f} d{mad[j]:.1f}',font=font,fill='white')
    b.save(p/f'audit/peaks_{k//8:03d}.jpg',quality=95)
print(json.dumps({'candidates':len(pool),'firstbatch':[x for x in recs if x['frame']<16000]}))
