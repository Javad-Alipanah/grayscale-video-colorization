import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
import unittest
from paired_neutral_entry import measured_alpha,parent_support_frames


class PairedSupportTest(unittest.TestCase):
    def setUp(self):
        self.shots=[dict(start_frame=10,end_frame=20,mode='colorize'),dict(start_frame=20,end_frame=30,mode='passthrough')]
        self.review=dict(recommended_trial_support_start_frame=18,recommended_trial_support_end_frame_exclusive=23,
            alpha_for_trial=[dict(frame_global=f,incoming_alpha=(f-18)/4) for f in range(18,23)])

    def test_continuous_source_alpha_spans_fixed_partition(self):
        self.assertEqual(measured_alpha(self.review,self.shots),{18:0,19:.25,20:.5,21:.75,22:1})

    def test_reject_missing_frame_or_non_neutral_incoming(self):
        bad=dict(self.review,alpha_for_trial=self.review['alpha_for_trial'][1:])
        with self.assertRaises(ValueError):measured_alpha(bad,self.shots)
        self.shots[1]['mode']='colorize'
        with self.assertRaises(ValueError):measured_alpha(self.review,self.shots)

    def test_reject_boundary_only_support_that_omits_reviewed_tail(self):
        bad=dict(self.review,recommended_trial_support_start_frame=20)
        with self.assertRaises(ValueError):measured_alpha(bad,self.shots)

    def test_two_neural_fields_require_explicit_mode_and_keep_crest_support(self):
        self.shots[1]['mode']='colorize'
        self.assertEqual(len(measured_alpha(self.review,self.shots,neural_incoming=True)),5)
        with self.assertRaises(ValueError):measured_alpha(self.review,self.shots)
        crest=dict(support_start_frame=79298,support_end_frame_exclusive=79525)
        self.assertEqual(parent_support_frames(crest),set(range(79298,79525)))
        compounded=dict(verified_support_union_global=[78641,78642,79298,79299])
        self.assertEqual(parent_support_frames(compounded),{78641,78642,79298,79299})

    def test_compact_native_receipt_preserves_four_frame_cross_partition_alpha(self):
        shots=[dict(start_frame=58480,end_frame=59059,mode='colorize'),
            dict(start_frame=59059,end_frame=59176,mode='passthrough')]
        review=dict(support_start_frame=59058,support_end_frame_exclusive=59062,
            incoming_alpha_for_trial=[.0384615384615,.079207920792,.377358490566,.951923076922])
        self.assertEqual(measured_alpha(review,shots),dict(zip(range(59058,59062),review['incoming_alpha_for_trial'])))
        with self.assertRaises(ValueError):
            measured_alpha(dict(review,incoming_alpha_for_trial=review['incoming_alpha_for_trial'][:-1]),shots)


if __name__=='__main__':unittest.main()
