"""Source/geometry/filename binding for public reference publication."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('reference_set', ROOT/'scripts/publish_reference_set.py')
r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r)


class ReferenceSetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.path = self.base/'ref_000012.png'
        Image.new('RGB', (16, 12), (80, 110, 130)).save(self.path)
        self.source = dict(sha256='source-hash', width=16, height=12)
        self.shot = dict(id='test', start_frame=240, end_frame=300)
        self.review = dict(status='approved', shot_id='test', source_sha256='source-hash',
            approved_by='test-reviewer', approved_at='2026-10-07', notes='synthetic validation fixture',
            geometry_checked=True, palette_checked=True, source_y_recombined_checked=True,
            references=[dict(path=self.path.name, sha256=r.pipeline.digest(self.path),
                source_frame=252, view='synthetic', materials=['flat color'])])

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_source_bound_set_is_accepted(self):
        self.assertEqual(len(r.validate(self.review, self.shot, self.source, self.base)), 1)

    def test_wrong_source_unreviewed_and_missing_visual_check_are_rejected(self):
        for key, value in [('source_sha256', 'other-film'), ('status', 'pending'), ('geometry_checked', False)]:
            review = copy.deepcopy(self.review)
            review[key] = value
            with self.assertRaises(ValueError):
                r.validate(review, self.shot, self.source, self.base)

    def test_changed_native_geometry_and_changed_hash_are_rejected(self):
        Image.new('RGB', (12, 12)).save(self.path)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            r.validate(self.review, self.shot, self.source, self.base)
        self.review['references'][0]['sha256'] = r.pipeline.digest(self.path)
        with self.assertRaisesRegex(ValueError, 'native-size'):
            r.validate(self.review, self.shot, self.source, self.base)

    def test_global_index_in_filename_and_duplicate_refs_are_rejected(self):
        self.review['references'][0]['source_frame'] = 253
        with self.assertRaisesRegex(ValueError, 'SHOT_LOCAL'):
            r.validate(self.review, self.shot, self.source, self.base)
        self.review['references'][0]['source_frame'] = 252
        self.review['references'] *= 2
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            r.validate(self.review, self.shot, self.source, self.base)


if __name__ == '__main__':
    unittest.main()
