import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
"""Source-Y preservation, coverage, and exact audio boundary checks."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / 'engine/delivery.py'
d = None
if SCRIPT.exists():
    spec = importlib.util.spec_from_file_location('delivery', SCRIPT)
    d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(d, 'Incremental source-Y delivery implementation is required')

    def test_original_y_bytes_are_untouched_by_predicted_chroma(self):
        y = bytes([0, 16, 235, 255])
        rgb = np.array([[[255, 0, 0], [0, 0, 0]], [[255, 255, 255], [128, 128, 128]]], dtype=np.uint8)
        packed = d.merge_frame(y, rgb)
        self.assertEqual(packed[:4], y)
        self.assertEqual(list(packed[4:8]), [90, 128, 128, 128])
        self.assertEqual(list(packed[8:12]), [240, 128, 128, 128])

    def test_audio_frame_boundaries_are_exact_samples(self):
        self.assertEqual(d.audio_sample_interval(0, 15017, 48000, 24000, 1001), (0, 30064034))
        self.assertEqual(d.audio_sample_interval(21579, 25899, 48000, 24000, 1001), (43201158, 51849798))
        self.assertEqual(d.audio_sample_interval(850, 1200, 48000, 24000, 1001)[0], 1701700)

    def test_batch_selection_rejects_gap_and_unverified_merge(self):
        shots = [{'id': 'a', 'start_frame': 0, 'end_frame': 2}, {'id': 'b', 'start_frame': 2, 'end_frame': 5}]
        merges = {s['id']: dict(s, frames=s['end_frame']-s['start_frame'], status='draft_verified',
            exact_source_y=True, full_decode_verified=True, output_sha256='hash') for s in shots}
        self.assertEqual(d.validate_merged_coverage(shots, merges), (0, 5))
        merges['b']['start_frame'] = 3
        with self.assertRaisesRegex(ValueError, 'coverage'):
            d.validate_merged_coverage(shots, merges)
        merges['b']['start_frame'] = 2
        merges['b']['exact_source_y'] = False
        with self.assertRaisesRegex(ValueError, 'verified'):
            d.validate_merged_coverage(shots, merges)


if __name__ == '__main__':
    unittest.main(verbosity=2)
