import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
"""Reject incomplete, failed or stale visual method evidence before activation."""
import tempfile
from pathlib import Path
from unittest import TestCase,main,mock
import production as p
import run_reviewed_batch02_corrections as runner

class GateTest(TestCase):
    def test_review_gate_requires_all_four_current_hash_bound_successes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);reviews=[];registry={}
            for index,shot in enumerate(sorted(runner.REQUIRED)):
                treatment=root/(shot+'_treatment.json')
                p.atomic_json(treatment,dict(method='source-measured-alpha two-sided per-frame neural UV blend v2; exact original Y',
                    full_decode_verified=True,exact_source_y=True,exact_outside_support_uv=True))
                review=root/(shot+'_review.json')
                p.atomic_json(review,dict(status='local_corrected_neighborhood_review_pass',output_sha256=str(index)))
                reviews.append(dict(shot_id=shot,review_path=str(review),review_sha256=p.sha256(review),output_sha256=str(index)))
                registry[shot]=dict(status='active_pending_quality_review',output_sha256=str(index),receipt=str(treatment))
            p.atomic_json(root/'source_y_overrides.json',registry)
            gate=root/'gate.json';record=dict(status='independent_method_visual_pass',delivery_acceptance=False,reviews=reviews)
            p.atomic_json(gate,record)
            with mock.patch.object(p,'HERE',root):
                self.assertEqual(len(runner.verify_method_gate(gate)['reviews']),4)
                incomplete=dict(record,reviews=reviews[:3]);p.atomic_json(gate,incomplete)
                with self.assertRaisesRegex(ValueError,'Both long'):runner.verify_method_gate(gate)
                p.atomic_json(gate,record)
                failed=p.read_json(reviews[0]['review_path']);failed['status']='changes_required'
                p.atomic_json(Path(reviews[0]['review_path']),failed)
                with self.assertRaisesRegex(ValueError,'review changed'):runner.verify_method_gate(gate)
                reviews[0]['review_sha256']=p.sha256(reviews[0]['review_path']);p.atomic_json(gate,record)
                with self.assertRaisesRegex(ValueError,'does not pass'):runner.verify_method_gate(gate)

if __name__=='__main__':main(verbosity=2)
