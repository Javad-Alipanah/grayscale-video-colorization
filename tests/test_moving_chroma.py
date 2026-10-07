import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
"""Real FFV1 integration: per-frame fields keep global positions and native Y."""
import hashlib
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase,main,mock
import production as p
import delivery as d
import boundary_chroma as b


class MovingFieldTest(TestCase):
    def test_real_lossless_per_frame_composite(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);pixels=256
            def video(name,uv_values,start):
                frames=[bytes([16+i,50+i,100+i,230-i])*64+bytes([u]*pixels+[v]*pixels) for i,(u,v) in enumerate(uv_values)]
                output=root/(name+'.mkv')
                subprocess.run([str(p.FFMPEG),'-v','error','-y','-f','rawvideo','-pix_fmt','yuv444p','-s','16x16','-framerate','24',
                    '-i','pipe:0','-an','-c:v','ffv1','-level','3',str(output)],input=b''.join(frames),check=True)
                record=dict(status='draft_verified',exact_source_y=True,full_decode_verified=True,output=str(output),output_sha256=p.sha256(output),
                    start_frame=start,end_frame=start+len(frames),frames=len(frames),source_y=dict(sha256=hashlib.sha256(b''.join(f[:pixels] for f in frames)).hexdigest()))
                return record,frames
            base,before=video('incoming',[(100,150),(120,170),(140,190),(160,210),(180,230)],2)
            outgoing,_=video('outgoing',[(25,30),(35,40)],0)
            overlap,_=video('overlap',[(10,20),(20,30),(40,50),(60,70)],0)
            shot=dict(id='incoming',start_frame=2,end_frame=7,frames=5)
            prior=dict(id='outgoing',start_frame=0,end_frame=2,frames=2)
            transition=dict(boundary_frame=2,support_start_frame=2,support_end_frame_exclusive=4,outgoing_anchor_frame=1,incoming_anchor_frames=[4,5,6],
                native_source_alpha=[dict(frame_global=2,alpha_incoming_for_review=.25),dict(frame_global=3,alpha_incoming_for_review=.75)])
            measurement=dict(source_sha256='source_fixture');path=root/'measurement.json';p.atomic_json(path,measurement)
            document=dict(source=dict(width=16,height=16,fps_num=24,fps_den=1))
            with mock.patch.object(d,'BASE',root/'delivery'),mock.patch.object(b,'STATUS',root/'status.json'):
                receipt,marker=b.repair(document,shot,prior,base,outgoing,transition,measurement,path,overlap=overlap)
            raw=subprocess.check_output([str(p.FFMPEG),'-v','error','-i',receipt['output'],'-f','rawvideo','-pix_fmt','yuv444p','pipe:1'])
            actual=[raw[i:i+3*pixels] for i in range(0,len(raw),3*pixels)]
            # Frame-global2 uses overlap local2, not local0 or a held endpoint.
            self.assertEqual(actual[0],before[0][:pixels]+bytes([55]*pixels+[75]*pixels))
            self.assertEqual(actual[1],before[1][:pixels]+bytes([105]*pixels+[145]*pixels))
            self.assertEqual(actual[2:],before[2:])
            self.assertTrue(receipt['exact_source_y'])
            self.assertTrue(receipt['exact_outside_support_uv'])
            self.assertTrue(receipt['full_decode_verified'])


if __name__=='__main__':main(verbosity=2)
