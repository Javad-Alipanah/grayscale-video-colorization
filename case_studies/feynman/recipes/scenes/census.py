from pathlib import Path
import subprocess,json,re,time
import numpy as np
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
FF=ROOT/'download-tools/ffmpeg.exe'
SRC=ROOT.parent/'outputs/Feynman_Source_Videos/Caltech_Restored/Lecture_01_Caltech_Restored.mkv'
# ROOT is work, not the workspace.
FPS=24000/1001
W,H=160,120
OUT.mkdir(parents=True,exist_ok=True)
raw=OUT/'census_gray_160x120.raw'
log=OUT/'decode_showinfo.log'
started=time.time()
if not raw.exists():
    with log.open('w',encoding='utf8') as err:
        subprocess.run([str(FF),'-hide_banner','-y','-i',str(SRC),'-an','-vf','showinfo,scale=160:120,format=gray','-fps_mode','passthrough','-pix_fmt','gray','-f','rawvideo',str(raw)],stderr=err,stdout=subprocess.DEVNULL,check=True)
assert raw.stat().st_size%(W*H)==0
n=raw.stat().st_size//(W*H)
pts=[]
for line in log.open(encoding='utf8'):
    m=re.search(r'\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:([0-9.e+-]+)',line)
    if m:
        assert int(m[1])==len(pts),(m[1],len(pts))
        pts.append(int(m[2]))
assert n==len(pts),(n,len(pts))
(OUT/'source_pts.json').write_text(json.dumps({'source_time_base':'1/1000','source_pts':pts,'first_pts_seconds':pts[0]/1000,'last_pts_seconds':pts[-1]/1000,'frame_count':n},indent=2))
a=np.memmap(raw,dtype=np.uint8,mode='r',shape=(n,H,W))
mad=np.zeros(n,np.float32);edge=mad.copy();hist=mad.copy();mean=mad.copy()
prev=a[0].astype(np.float32); pe=np.diff(prev,axis=1);ph=np.bincount(a[0].ravel()//8,minlength=32)/(W*H)
mean[0]=prev.mean()
for i in range(1,n):
    cur=a[i].astype(np.float32);ce=np.diff(cur,axis=1);ch=np.bincount(a[i].ravel()//8,minlength=32)/(W*H)
    mad[i]=np.abs(cur-prev).mean();edge[i]=np.abs(ce-pe).mean();hist[i]=np.abs(ch-ph).sum();mean[i]=cur.mean()
    prev,pe,ph=cur,ce,ch
np.savez_compressed(OUT/'cut_scores.npz',mad=mad,edge=edge,histogram_l1=hist,mean=mean)
font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',17)
def board(ids,name,cols=4):
    b=Image.new('RGB',(320*cols,((len(ids)+cols-1)//cols)*264),'#161616');d=ImageDraw.Draw(b)
    for k,i in enumerate(ids):
        x=k%cols*320;y=k//cols*264
        b.paste(Image.fromarray(a[i]).resize((320,240)),(x,y+24))
        t=pts[i]/1000
        d.text((x+3,y+2),f'{i:05d} {int(t)//60:02d}:{t%60:05.2f} d={mad[i]:.1f}',font=font,fill='white')
    b.save(OUT/name,quality=92)
ids=list(range(0,n,240))+[n-1]
for k in range(0,len(ids),32):board(ids[k:k+32],f'overview/ten_seconds_{k//32:02d}.jpg')
# Candidate peaks separated 12 frames; gradual dissolves still peak consistently.
score=np.maximum(mad/8,edge/10)
rawpeaks=np.where((score>1)|(hist>.22))[0]
peaks=[]
for i in rawpeaks:
    if i<2:continue
    if peaks and i-peaks[-1]<12:
        if score[i]>score[peaks[-1]]:peaks[-1]=int(i)
    else:peaks.append(int(i))
rec=[{'frame':i,'pts_seconds':pts[i]/1000,'mad':float(mad[i]),'edge':float(edge[i]),'histogram_l1':float(hist[i])} for i in peaks]
(OUT/'cut_candidates.json').write_text(json.dumps(rec,indent=2))
for k in range(0,len(peaks),8):
    ids=[max(0,min(n-1,i+delta)) for i in peaks[k:k+8] for delta in [-3,-1,0,3]]
    board(ids,f'candidates/cuts_{k//8:03d}.jpg')
summary={'frame_count':n,'duration_frames_seconds':n/FPS,'first_pts':pts[0],'last_pts':pts[-1],'candidate_count':len(peaks),'max_mad':float(mad.max()),'elapsed_seconds':time.time()-started}
(OUT/'census_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary),flush=True)
