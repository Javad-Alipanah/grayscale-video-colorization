import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
import tempfile
from pathlib import Path
import unittest
import production as p
from run_bounded_mask_trial import verified_completed_trial, validate_bidirectional_scope

class BoundedMaskResume(unittest.TestCase):
    def test_retained_complete_trial_bypasses_gpu_but_pixel_tamper_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);mask=root/'native_mask.bin';mask.write_bytes(b'original mask bytes')
            external=root/'source_plan.json';p.atomic_json(external,{'scope':[10,11]})
            direction=root/'trial.json'
            p.atomic_json(direction,dict(plan_sha256=p.sha256(external),script_sha256='frozen_runner',
                records=[dict(frame_global=10,mask_path=str(mask),mask_sha256=p.sha256(mask))]))
            receipt=root/'verification.json';p.atomic_json(receipt,dict(status='bounded_mask_trial_integrity_pass_visual_QA_pending',
                source_sha256='source',frames=1,receipts=[dict(path=str(direction),sha256=p.sha256(direction))]))
            plan=dict(status='bounded_mask_trial_complete_pending_QA',kind='bidirectional_source_foreground_trial',
                result_receipt=str(receipt),result_receipt_sha256=p.sha256(receipt),source_sha256='source',frames=1,
                source_trial_plan=str(external),source_trial_plan_sha256=p.sha256(external),script_sha256='frozen_runner')
            self.assertTrue(verified_completed_trial(plan))
            mask.write_bytes(b'changed mask bytes')
            with self.assertRaisesRegex(ValueError,'pixels changed'):verified_completed_trial(plan)

    def test_incomplete_scope_does_not_claim_resume(self):
        self.assertFalse(verified_completed_trial({'status':'trial_rendering'}))

    def test_board_foreground_scope_requires_exact_frozen_plan_and_count(self):
        external={'jobs':[{'start_frame':a,'end_frame':b} for a,b in
            [(76493,76670),(77070,77278),(77278,77494),(77494,77633)]]}
        plan={'frames':744,'authorized_frame_limit':744,
            'source_trial_plan_sha256':'b6159aadd70373488b72eb8394f31ab9d2460aa73bddd2f87b39dd6374c57832'}
        validate_bidirectional_scope(plan,external)
        with self.assertRaisesRegex(ValueError,'frozen source scope'):
            validate_bidirectional_scope({**plan,'source_trial_plan_sha256':'different'},external)
        with self.assertRaisesRegex(ValueError,'exceeds'):
            validate_bidirectional_scope({**plan,'frames':745},external)

if __name__=='__main__':unittest.main()
