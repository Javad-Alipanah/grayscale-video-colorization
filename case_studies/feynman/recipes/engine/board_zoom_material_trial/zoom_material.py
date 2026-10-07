"""Pure source-bound chroma gate shared by the unselected zoom material trial."""
import numpy as np
import cv2
from PIL import Image,ImageDraw
cv2.setNumThreads(2)
def smooth(a):
 a=np.clip(a,0,1);return a*a*(3-2*a)
def alpha(before,row,actor):
 plane=Image.new('L',(960,720));draw=ImageDraw.Draw(plane)
 for polygon in row['screen_polygons_native']:draw.polygon([tuple(x) for x in polygon],fill=255)
 for item in row['source_object_exclusions']:draw.polygon([tuple(x) for x in item['polygon_native']],fill=0)
 core=actor>0
 guard=cv2.dilate(core.astype(np.uint8),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(17,17)))>0
 region=np.array(plane)>0;region[guard]=False
 feather=smooth((cv2.distanceTransform(region.astype(np.uint8),cv2.DIST_L2,5)-.5)/8)
 uv=before[1:].astype(np.float32)
 warm=smooth((uv[1]-125.5)/5)
 chroma=smooth((np.sqrt(((uv-128)**2).sum(axis=0))-3)/3)
 chalk=1-smooth((before[0].astype(np.float32)-170)/40)
 a=np.rint(feather*warm*chroma*chalk*255).astype(np.uint8)
 assert not a[core].any()
 return a,guard
