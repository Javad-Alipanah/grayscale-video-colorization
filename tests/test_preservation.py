"""Real FFmpeg tests using generated video and a longer audio tail."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('preservation', ROOT/'scripts/verify_preservation.py')
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)
FF = os.environ.get('COLOR_FFMPEG', shutil.which('ffmpeg'))
FP = os.environ.get('COLOR_FFPROBE', shutil.which('ffprobe'))


@unittest.skipUnless(FF and FP, 'FFmpeg and ffprobe required for media integration tests')
class PreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        cls.source = cls.base/'source.mkv'
        cls.master = cls.base/'master.mkv'
        cls.runff('-f', 'lavfi', '-i', 'testsrc2=size=64x48:rate=24:duration=1',
                  '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1.2',
                  '-c:v', 'ffv1', '-pix_fmt', 'yuv420p', '-color_range', 'tv',
                  '-colorspace', 'smpte170m', '-c:a', 'pcm_f32le', str(cls.source))
        cls.runff('-i', str(cls.source), '-vf', 'format=yuv444p,lut=u=160:v=110',
                  '-c:v', 'ffv1', '-c:a', 'copy', str(cls.master))

    @classmethod
    def runff(cls, *args):
        subprocess.run([FF, '-v', 'error', '-y', *args], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_chroma_can_change_while_all_y_audio_and_pts_match(self):
        result = v.verify(self.source, self.master, FF, FP)
        self.assertEqual(result['frame_count'], 24)
        self.assertEqual(result['original_audio']['bytes'], 57600*4)
        self.assertFalse(result['visual_acceptance'])

    def test_changed_luma_is_rejected(self):
        bad = self.base/'bad_y.mkv'
        self.runff('-i', str(self.master), '-vf', 'lut=y=val+1', '-c:v', 'ffv1', '-c:a', 'copy', str(bad))
        with self.assertRaisesRegex(ValueError, 'Original Y'):
            v.verify(self.source, bad, FF, FP)

    def test_audio_tail_loss_is_rejected(self):
        bad = self.base/'bad_audio.mkv'
        self.runff('-i', str(self.master), '-af', 'atrim=end=1', '-c:v', 'copy', '-c:a', 'pcm_f32le', str(bad))
        with self.assertRaisesRegex(ValueError, 'audio through natural EOF'):
            v.verify(self.source, bad, FF, FP)

    def test_aac_priming_is_compared_on_decoded_sample_clock(self):
        source = self.base/'aac_source.mkv'
        master = self.base/'aac_decoded_master.mkv'
        self.runff('-i', str(self.source), '-c:v', 'copy', '-c:a', 'aac', '-avoid_negative_ts', 'disabled', str(source))
        self.runff('-copyts', '-i', str(source), '-c:v', 'copy', '-c:a', 'pcm_f32le', str(master))
        result = v.verify(source, master, FF, FP)
        self.assertIn('codec priming honored', result['original_audio']['policy'])

    def test_large_pts_tolerance_is_not_an_escape_hatch(self):
        with self.assertRaisesRegex(ValueError, 'between 0 and 1'):
            v.verify(self.source, self.master, FF, FP, pts_tolerance_ms=1000)

    def test_retagged_color_matrix_is_rejected(self):
        bad = self.base/'bad_matrix.mkv'
        self.runff('-i', str(self.master), '-c', 'copy', '-colorspace', 'bt709', str(bad))
        with self.assertRaisesRegex(ValueError, 'Display interpretation'):
            v.verify(self.source, bad, FF, FP)

    def test_shifted_timestamps_are_rejected(self):
        bad = self.base/'bad_pts.mkv'
        self.runff('-i', str(self.master), '-vf', 'setpts=PTS+1/TB', '-fps_mode', 'passthrough',
                   '-c:v', 'ffv1', '-c:a', 'copy', str(bad))
        with self.assertRaisesRegex(ValueError, 'timestamp'):
            v.verify(self.source, bad, FF, FP)

    def test_immutable_range_requires_exact_yuv(self):
        good = v.verify(self.source, self.master, FF, FP, self.master, 0)
        self.assertEqual(good['immutable_reuse']['end_frame'], 24)
        wrong = self.base/'wrong_uv.mkv'
        self.runff('-i', str(self.master), '-vf', 'lut=u=170', '-c:v', 'ffv1', '-c:a', 'copy', str(wrong))
        with self.assertRaisesRegex(ValueError, 'Immutable native YUV'):
            v.verify(self.source, self.master, FF, FP, wrong, 0)


if __name__ == '__main__':
    unittest.main()
