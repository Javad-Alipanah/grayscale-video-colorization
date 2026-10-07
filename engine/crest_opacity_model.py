"""Original-source stroke opacity for a strictly bounded CPU chroma trial."""
import cv2
import numpy as np


class SourceCrestOpacity:
    def __init__(self,samples):
        cv2.setNumThreads(2)
        self.source={f:samples[f'source_{f}'].copy() for f in [79297,79325,79421,79525]}
        self.height,self.width=self.source[79297][0].shape
        h,w=self.height,self.width
        self.outside=np.ones((h,w),np.uint8)*255
        self.outside[90:660,235:695]=0;self.outside[:25]=0;self.outside[690:]=0;self.outside[:,:20]=0;self.outside[:,935:]=0
        region=np.zeros((h,w),np.uint8);region[100:645,245:685]=1
        plates={f:self.plate(f,self.source[f][0])[0] for f in [79325,79421]}
        peak=np.median(np.stack([self.source[f][0].astype(np.float32)-plates[f] for f in [79325,79421]]),axis=0)
        peak_y=np.median(np.stack([self.source[f][0] for f in [79325,79421]]),axis=0)
        ink_white=float(np.percentile(peak_y[(peak>60)&(region>0)],98))
        background=np.median(np.stack(list(plates.values())),axis=0)
        template=np.clip(peak/np.maximum(ink_white-background,12),0,1)*region
        near_core=cv2.dilate((template>.45).astype(np.uint8),np.ones((5,5),np.uint8)).astype(bool)
        envelope=np.zeros((h,w),np.uint8)
        cv2.fillPoly(envelope,[np.array([[241,100],[686,100],[686,424],[660,491],[600,541],[464,650],
            [327,561],[258,492],[241,427]],np.int32)],1)
        self.mask=near_core&(envelope>0)
        template*=self.mask
        self.peak=peak;self.core=(template>.75)&(peak>50)
        self.local_white=np.maximum(np.minimum(ink_white,cv2.dilate(peak_y.astype(np.float32),np.ones((9,9),np.uint8))+1),background+12)

    def plate(self,frame,current):
        estimates=[];proof=[]
        for anchor_frame in [79297,79525]:
            anchor=self.source[anchor_frame][0]
            points=cv2.goodFeaturesToTrack(anchor,maxCorners=700,qualityLevel=.01,minDistance=7,mask=self.outside)
            tracked,ok,error=cv2.calcOpticalFlowPyrLK(anchor,current,points,None,winSize=(31,31),maxLevel=3)
            valid=ok[:,0].astype(bool)&(error[:,0]<20)
            transform,inliers=cv2.estimateAffinePartial2D(points[valid],tracked[valid],method=cv2.RANSAC,ransacReprojThreshold=1.5)
            if transform is None or int(inliers.sum())<30:raise ValueError('Insufficient source-only background geometry')
            warped=cv2.warpAffine(anchor.astype(np.float32),transform,(self.width,self.height),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)
            selected=(self.outside>0)&(warped>35)&(warped<210)
            x=warped[selected][::8];y=current[selected][::8]
            gain,offset=np.linalg.lstsq(np.stack([x,np.ones_like(x)],axis=1),y,rcond=None)[0]
            warped=np.clip(warped*gain+offset,16,235).astype(np.float32)
            proof.append(dict(anchor_frame=anchor_frame,transform=transform.tolist(),inliers=int(inliers.sum()),
                gain=float(gain),offset=float(offset),median_native_y_residual=float(np.median(np.abs(warped[selected]-current[selected])))))
            estimates.append(warped)
        t=float(np.clip((frame-79297)/(79525-79297),0,1))
        return estimates[0]*(1-t)+estimates[1]*t,proof

    def apply(self,frame,source,baseline):
        if not np.array_equal(source[0],baseline[0]):raise ValueError('Source/current original-Y mapping differs')
        if not 79298<=frame<79525:return baseline.copy(),np.zeros_like(self.mask),dict(strength=0,geometry=[])
        background,geometry=self.plate(frame,source[0]);y=source[0].astype(np.float32)
        dynamic=np.clip((y-background)/np.maximum(self.local_white-background,12),0,1)
        strength=float(np.clip(np.median((y-background)[self.core]/np.maximum(self.peak[self.core],1)),0,1))
        alpha=np.minimum(dynamic,strength)*self.mask
        alpha[dynamic<.025]=0
        corrected=np.rint(baseline[1:].astype(np.float32)*(1-alpha)+source[1:].astype(np.float32)*alpha).clip(0,255).astype(np.uint8)
        after=baseline.copy();after[1:,self.mask]=corrected[:,self.mask]
        after[1:,alpha==0]=baseline[1:,alpha==0]
        return after,alpha,dict(strength=strength,geometry=geometry)
