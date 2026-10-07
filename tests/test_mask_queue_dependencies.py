import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
import unittest
from unittest.mock import patch
import run_bounded_mask_trial as trial
import run_ordered_remaining_repairs as repairs


class MaskQueueDependenciesTest(unittest.TestCase):
    def test_primary_must_be_complete_and_have_no_active_worker(self):
        plan={'dependency_queue_status':'status.json','dependency_expected_frames':7947}
        state={'stage':'queue_complete','selected_rendered_frames':7947,'selected_expected_frames':7947,'active':None}
        with patch.object(trial.Path,'exists',return_value=True),patch.object(trial.p,'read_json',return_value=state):
            self.assertTrue(trial.dependency_ready(plan))
            for field,value in [('stage','rendering'),('selected_rendered_frames',2386),('selected_expected_frames',80026),('active',{'worker_pid':123})]:
                altered=dict(state,**{field:value})
                with patch.object(trial.p,'read_json',return_value=altered):
                    self.assertFalse(trial.dependency_ready(plan))

    def test_following_repairs_wait_for_both_integrity_receipts(self):
        plan={'before_gpu_dependencies':['first.json','second.json']}
        states={'first.json':{'status':'bounded_mask_trial_complete_pending_QA'},'second.json':{'status':'trial_rendering'}}
        with patch.object(repairs.Path,'exists',return_value=True),patch.object(repairs.p,'read_json',side_effect=lambda path:states[str(path)]):
            self.assertEqual(repairs.pending_before_gpu_dependencies(plan),['second.json'])
            states['second.json']['status']='failed'
            self.assertEqual(repairs.pending_before_gpu_dependencies(plan),['second.json'])
            states['second.json']['status']='bounded_mask_trial_complete_pending_QA'
            self.assertEqual(repairs.pending_before_gpu_dependencies(plan),[])


if __name__=='__main__':unittest.main()
