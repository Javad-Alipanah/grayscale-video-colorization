from pathlib import Path
import numpy as np,json
from scipy.ndimage import median_filter,maximum_filter1d
from PIL import Image,ImageDraw,ImageFont
p=Path(__file__).parent;n=80026;a=np.memmap(p/'census_gray_160x120.raw',dtype=np.uint8,mode='r',shape=(n,120,160))
original=[r['frame'] for r in json.loads((p/'audit_candidates.json').read_text())]
f=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',17)
scores=[]
for lag in [8,24]:
    score=np.zeros(n,np.float32)
    for i in range(lag,n):score[i]=np.abs(a[i].astype(np.float32)-a[i-lag].astype(np.float32)).mean()
    measure=score/(2+median_filter(score,size=199));peaks=np.where((measure>3)&(score>12)&(measure==maximum_filter1d(measure,size=49)))[0]
    scores.extend([{'peak':int(i),'lag':lag,'ratio':float(measure[i]),'difference':float(score[i])} for i in peaks if min(abs(i-lag//2-o) for o in original)>30])
scores.sort(key=lambda r:r['peak']);(p/'supplement_candidates.json').write_text(json.dumps(scores,indent=2))
for k in range(0,len(scores),8):
    group=scores[k:k+8];b=Image.new('RGB',(1280,len(group)*264),'#161616');d=ImageDraw.Draw(b)
    for r,rec in enumerate(group):
        i=rec['peak'];lag=rec['lag']
        for c,j in enumerate([max(0,i-lag-12),max(0,i-lag),i,min(n-1,i+12)]):
            x=c*320;y=r*264;b.paste(Image.fromarray(a[j]).resize((320,240)),(x,y+24));d.text((x+2,y+1),f'{j} {j*1001/24000:.3f}s lag{lag}',font=f,fill='white')
    b.save(p/f'audit/supplement_{k//8:02d}.jpg',quality=95)
print(json.dumps({'new_candidates':len(scores),'records':scores}))
