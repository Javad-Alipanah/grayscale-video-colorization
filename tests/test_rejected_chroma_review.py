import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
"""Independent local rejection must hold delivery even after registry republication."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import production as p
import delivery as d


class RejectedReviewTests(unittest.TestCase):
    def test_exact_payload_rejection_and_pass_scopes(self):
        with tempfile.TemporaryDirectory(dir=p.HERE) as folder, patch.object(p, 'PROJECT', Path(folder)):
            shot='shot_059176';digest='a'*64
            path=p.PROJECT/'scenes/qc/dissolves/corrections'/shot/digest[:12]/'visual_review.json'
            for status in ['changes_required_at_join','local_transition_reject','local_neighborhood_rejected']:
                p.atomic_json(path,dict(shot_id=shot,output_sha256=digest,status=status))
                with self.assertRaises(p.QualityReviewRejected):p.reject_failed_chroma_review(shot,digest)
            for overrides in [dict(status='local_corrected_neighborhood_review_pass'),dict(shot_id='another'),dict(output_sha256='b'*64)]:
                p.atomic_json(path,dict(dict(shot_id=shot,output_sha256=digest,status='local_transition_reject'),**overrides))
                p.reject_failed_chroma_review(shot,digest)

    def test_explicit_held_registry_fails_before_loading_media(self):
        with self.assertRaises(p.QualityReviewRejected):
            d.apply_source_y_override(dict(shot_id='shot_059176'),{'shot_059176':dict(status='changes_required')})


if __name__=='__main__':unittest.main(verbosity=2)
