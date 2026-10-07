"""Read-only source strips for physical-plane geometry annotation."""
from pathlib import Path
import json, hashlib
from PIL import Image, ImageDraw, ImageFont
B=Path(__file__).resolve().parent
S=B.parent/'source_survey_v01'
rows=[r for r in json.loads((S/'sampling.json').read_text())['records'] if r['frame_global']>=27193]
font=ImageFont.truetype('C:/Windows/Fonts/consola.ttf',16)
for off in range(0,len(rows),10):
    sheet=Image.new('RGB',(1060,140*len(rows[off:off+10])),(25,25,25));d=ImageDraw.Draw(sheet)
    for j,r in enumerate(rows[off:off+10]):
        im=Image.open(r['source']).convert('RGB'); y=j*140
        sheet.paste(im.crop((0,12,960,122)),(100,y+25))
        d.text((3,y+45),str(r['frame_global']),font=font,fill='white')
        for x in range(0,960,100):
            d.text((x+102,y+4),str(x),font=font,fill='yellow')
            d.line((x+100,y+23,x+100,y+34),fill='yellow')
    sheet.save(B/f'upper_strips_{off//10:02}.png')
print(len(rows),'source strips')
