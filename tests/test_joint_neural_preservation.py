import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
"""Exercise real FFV1 joint compositing with a disjoint preselected crest patch."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import production as p
import delivery as d
import paired_neutral_entry as joint

class JointNeuralPreservation(unittest.TestCase):
    def test_joint_split_retains_all_Y_and_disjoint_crest_native_bytes(self):
        pixels=16*12
        source=dict(width=16,height=12,fps_num=24000,fps_den=1001)
        document=dict(source=source)
        shots=[dict(id='left',start_frame=0,end_frame=3,frames=3,mode='colorize'),
               dict(id='right',start_frame=3,end_frame=9,frames=6,mode='colorize')]
        def frame(index,u,v):return bytes([16+index])*pixels+bytes([u])*pixels+bytes([v])*pixels
        with tempfile.TemporaryDirectory() as directory,patch.object(d,'BASE',Path(directory)):
            directory=Path(directory)
            def encode(name,start,frames):
                path=directory/(name+'.mkv')
                command=[str(p.FFMPEG),'-v','error','-y','-f','rawvideo','-pix_fmt','yuv444p','-s','16x12','-framerate','24000/1001',
                    '-i','pipe:0','-an','-c:v','ffv1','-level','3','-threads','1','-pix_fmt','yuv444p',str(path)]
                subprocess.run(command,input=b''.join(frames),check=True,capture_output=True)
                return dict(status='draft_verified',output=str(path),output_sha256=p.sha256(path),start_frame=start,end_frame=start+len(frames),frames=len(frames),
                    exact_source_y=True,full_decode_verified=True,source_y=dict(sha256=hashlib.sha256(b''.join(x[:pixels] for x in frames)).hexdigest(),decoded_bytes=len(frames)*pixels))
            base_frames=[frame(i,110,140) for i in range(9)]
            bases=[encode('left',0,base_frames[:3]),encode('right',3,base_frames[3:])]
            for shot,base in zip(shots,bases):base['shot_id']=shot['id']
            prior_frames=base_frames[3:7]+[frame(i,128,128) for i in range(7,9)]
            prior=encode('crest',3,prior_frames);prior['shot_id']='right'
            crest=dict(output_sha256=prior['output_sha256'],base_output_sha256=bases[1]['output_sha256'],support_start_frame=7,support_end_frame_exclusive=9)
            crest_path=directory/'crest.json';p.atomic_json(crest_path,crest)
            outgoing=encode('outgoing',0,[frame(i,100,150) for i in range(5)])
            incoming=encode('incoming',2,[frame(i,140,110) for i in range(2,9)])
            review=directory/'review.json';p.atomic_json(review,dict(source_sha256='original',support_start_frame=2,support_end_frame_exclusive=5,incoming_alpha_for_trial=[0,.5,1]))
            result,_=joint.build(document,shots,bases,[bases[0],prior],[None,dict(receipt=str(crest_path))],outgoing,
                dict(sha256='original'),review,lambda **kw:None,incoming_overlap=incoming)
            expected={0:base_frames[0],1:base_frames[1],2:frame(2,100,150),3:frame(3,120,130),4:frame(4,140,110),
                      5:base_frames[5],6:base_frames[6],7:frame(7,128,128),8:frame(8,128,128)}
            for shot,part in zip(shots,result['parts']):
                decoded=subprocess.check_output([str(p.FFMPEG),'-v','error','-i',part['output'],'-pix_fmt','yuv444p','-f','rawvideo','pipe:1'])
                self.assertEqual(decoded,b''.join(expected[i] for i in range(shot['start_frame'],shot['end_frame'])))
            self.assertEqual(result['parts'][1]['verified_support_union_global'],[3,4,7,8])
            self.assertNotIn('outgoing_output_sha256',result['parts'][0])
            self.assertTrue(all(x['exact_previous_treatment_preserved'] for x in result['parts']))

if __name__=='__main__':unittest.main()
