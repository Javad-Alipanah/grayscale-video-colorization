import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
"""Reviewed compound treatments may depend on an exact selected prior shot."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import delivery as d


class SelectedOutgoingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bases = {}
        self.registry = {}
        for sid, start in [('prior', 0), ('target', 10)]:
            base_hash = sid + '-base'
            base = dict(shot_id=sid, start_frame=start, end_frame=start+10,
                        frames=10, output=sid+'-base.mkv', output_sha256=base_hash)
            self.bases[sid] = base
            media = self.root / (sid+'.mkv')
            media.write_bytes((sid+' selected').encode())
            digest = hashlib.sha256(media.read_bytes()).hexdigest()
            row = dict(base, base_output_sha256=base_hash, output=str(media),
                       output_sha256=digest, status='draft_verified', method='test',
                       exact_source_y=True, full_decode_verified=True,
                       exact_outside_support_uv=True)
            receipt = self.root/(sid+'.json')
            receipt.write_text(json.dumps(row))
            self.registry[sid] = dict(receipt=str(receipt), output_sha256=digest)
        self.target = Path(self.registry['target']['receipt'])
        row = json.loads(self.target.read_text())
        row.update(outgoing_shot_id='prior', outgoing_output_sha256=self.registry['prior']['output_sha256'])
        self.target.write_text(json.dumps(row))

    def apply(self):
        with patch.object(d.p, 'reject_failed_chroma_review'):
            return d.apply_source_y_override(self.bases['target'], self.registry, self.bases)

    def test_exact_selected_prior_is_validated_and_resolved(self):
        self.assertEqual(self.apply()['output_sha256'], self.registry['target']['output_sha256'])

    def test_prior_selection_or_media_change_fails_closed(self):
        expected = self.registry['prior']['output_sha256']
        self.registry['prior']['output_sha256'] = 'different'
        with self.assertRaisesRegex(ValueError, 'outgoing base changed'):
            self.apply()
        self.registry['prior']['output_sha256'] = expected
        (self.root/'prior.mkv').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'payload changed'):
            self.apply()

    def test_nonadjacent_or_unverified_selected_prior_is_rejected(self):
        self.bases['prior']['end_frame'] = 9
        with self.assertRaisesRegex(ValueError, 'outgoing base changed'):
            self.apply()
        self.bases['prior']['end_frame'] = 10
        path = Path(self.registry['prior']['receipt'])
        row = json.loads(path.read_text()); row['exact_source_y'] = False
        path.write_text(json.dumps(row))
        with self.assertRaisesRegex(ValueError, 'proof'):
            self.apply()


if __name__ == '__main__':
    unittest.main(verbosity=2)
