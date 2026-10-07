import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
import unittest
from run_ordered_remaining_repairs import dependency_complete
from queue_after_plan import dependency_inference_ready

class OrderedDependencyTests(unittest.TestCase):
    def test_finalized_candidates_and_drafts_release_inference_dependency(self):
        for stage in ['overlap_inference_complete','draft_per_frame_treatments_ready','revised_drafts_ready_pending_review','source_y_candidate_ready_pending_dense_QA','bounded_mask_trial_complete_pending_QA']:
            self.assertTrue(dependency_inference_ready(dict(status=stage)))
        for stage in ['running','queued_candidate_after_batch04','failed','queued_after_audience','trial_rendering']:
            self.assertFalse(dependency_inference_ready(dict(status=stage)))

    def test_individual_shot_completion_cannot_release_the_next_queue(self):
        self.assertFalse(dependency_complete(dict(stage='rendering',selected_expected_frames=14836,selected_rendered_frames=14835),14836))
        self.assertFalse(dependency_complete(dict(stage='queue_complete',selected_expected_frames=1073,selected_rendered_frames=1073),14836))
        self.assertFalse(dependency_complete(dict(stage='queue_complete',selected_expected_frames=14836,selected_rendered_frames=14835),14836))
        self.assertTrue(dependency_complete(dict(stage='queue_complete',selected_expected_frames=14836,selected_rendered_frames=14836),14836))

if __name__=='__main__':unittest.main(verbosity=2)
