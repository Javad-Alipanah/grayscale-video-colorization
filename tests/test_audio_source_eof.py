import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
"""Real PCM regression: the final video boundary may exceed source audio EOF."""
import hashlib
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import numpy as np
import delivery as d
import production as p


class AudioEOFTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=p.HERE/'smoke/audio_eof';cls.root.mkdir(parents=True,exist_ok=True)
        cls.audio=cls.root/'original.mka'
        cls.samples=(np.arange(23000,dtype=np.float32).reshape(11500,2)/23000).astype('<f4')
        subprocess.run([str(p.FFMPEG),'-v','error','-y','-f','f32le','-ar','48000','-ac','2','-i','pipe:0','-c:a','pcm_f32le',str(cls.audio)],input=cls.samples.tobytes(),check=True)
        cls.identity=dict(path=str(cls.audio),sha256=p.sha256(cls.audio))

    def prepare(self,start,end,frame_count,name):
        directory=self.root/name;directory.mkdir(exist_ok=True)
        document={'source':dict(frame_count=frame_count,fps_num=24000,fps_den=1001)}
        def run(command,logfile,callback=None):
            with Path(logfile).open('w') as log:subprocess.run(command,stdout=log,stderr=log,check=True)
        with patch.object(d,'run_logged',side_effect=run):
            return d.prepare_audio(document,start,end,self.identity,directory,lambda **_:None)

    def test_final_partial_batch_preserves_every_remaining_sample(self):
        result=self.prepare(4,6,6,'final_tail')
        self.assertEqual(result['samples_per_channel'],3492)
        self.assertEqual(result['source_audio']['sha256'],hashlib.sha256(self.samples[8008:].tobytes()).hexdigest())
        self.assertEqual(tuple(result['selected_sample_interval']),(8008,None))

    def test_internal_batch_boundary_is_still_exact(self):
        result=self.prepare(4,5,6,'interior')
        self.assertEqual(result['samples_per_channel'],2002)
        self.assertEqual(result['source_audio']['sha256'],hashlib.sha256(self.samples[8008:10010].tobytes()).hexdigest())

    def test_source_shortfall_before_an_internal_boundary_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'audio ended'):
            self.prepare(4,6,7,'invalid_short_interior')


if __name__=='__main__':unittest.main()
