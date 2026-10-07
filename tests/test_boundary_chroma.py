import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
"""Boundary treatment must preserve luminance and bind the exact reviewed base."""
import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path
import numpy as np
import production as p
import delivery as d
try:
    import boundary_chroma as b
except ImportError:
    b = None


class BoundaryTests(unittest.TestCase):
    def test_per_frame_field_accepts_one_reviewed_anchor_without_weakening_held_mode(self):
        plan=dict(boundary_frame=10,support_start_frame=10,support_end_frame_exclusive=12,outgoing_anchor_frame=9,
            incoming_anchor_frames=[12],native_source_alpha=[dict(frame_global=10,alpha_incoming_for_review=.2),dict(frame_global=11,alpha_incoming_for_review=.8)])
        shot=dict(start_frame=10,end_frame=20)
        self.assertEqual(b.validate_transition(plan,shot,per_frame=True),{10:.2,11:.8})
        with self.assertRaises(ValueError):b.validate_transition(plan,shot)
        plan['incoming_anchor_frames']=[11]
        with self.assertRaises(ValueError):b.validate_transition(plan,shot,per_frame=True)
    def test_native_hardcut_override_rejects_the_old_dissolve_ramp(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(p,'HERE',Path(tmp)):
            review=Path(tmp)/'review.json';p.atomic_json(review,dict(status='source_hardcut_timing_review_pass',actual_hardcut_first_incoming_frame=11))
            p.atomic_json(Path(tmp)/'source_timing_overrides.json',{'10':dict(review=str(review),review_sha256=p.sha256(review),first_incoming_frame=11)})
            old=dict(boundary_frame=10,support_start_frame=10,support_end_frame_exclusive=12,outgoing_anchor_frame=9,
                incoming_anchor_frames=[12,13,14],native_source_alpha=[dict(frame_global=10,alpha_incoming_for_review=.3),dict(frame_global=11,alpha_incoming_for_review=.7)])
            with self.assertRaisesRegex(ValueError,'Superseded'):
                b.validate_transition(old,dict(start_frame=10,end_frame=20))
            corrected=b.resolve_source_timing(old)
            self.assertEqual(b.validate_transition(corrected,dict(start_frame=10,end_frame=20)),{10:0.0})
            self.assertEqual(corrected['support_end_frame_exclusive'],11)

    def test_cross_batch_override_resolves_only_verified_adjacent_baseline(self):
        target=dict(id='incoming',start_frame=20,end_frame=30)
        outgoing=dict(id='outgoing',start_frame=10,end_frame=20)
        base=dict(shot_id='incoming',start_frame=20,end_frame=30,output_sha256='in')
        native=dict(shot_id='outgoing',start_frame=10,end_frame=20,output_sha256='out')
        with tempfile.TemporaryDirectory() as tmp:
            marker=Path(tmp)/'treatment.json';p.atomic_json(marker,dict(outgoing_shot_id='outgoing',outgoing_output_sha256='out'))
            registry={'incoming':dict(receipt=str(marker))}
            with patch.object(d,'choose_attempt',return_value={'verified':True}) as choose, patch.object(d,'merge_one',return_value=native) as merge, patch.object(d,'reviewed_reclaimed_base',return_value=None):
                result=d.override_base_context(dict(shots=[outgoing,target]),{'incoming':base},registry,{}, {},lambda **k:None)
                self.assertEqual(result,{'incoming':base,'outgoing':native})
                choose.assert_called_once();merge.assert_called_once()
                outgoing['end_frame']=19
                with self.assertRaisesRegex(ValueError,'adjacent'):
                    d.override_base_context(dict(shots=[outgoing,target]),{'incoming':base},registry,{}, {},lambda **k:None)

    def test_rejected_payload_cannot_be_reactivated_by_a_fresh_registry(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(p, 'PROJECT', Path(tmp)):
            output = Path(tmp)/'rejected.mkv'; output.write_bytes(b'rejected draft')
            digest = p.sha256(output)
            receipt = dict(status='draft_verified',exact_source_y=True,full_decode_verified=True,
                exact_outside_support_uv=True,base_output_sha256='base',output=str(output),output_sha256=digest,
                shot_id='shot_test',start_frame=10,end_frame=20,frames=10,method='measured blend')
            marker=Path(tmp)/'treatment.json'; p.atomic_json(marker,receipt)
            review=Path(tmp)/'scenes/qc/dissolves/corrections/shot_test'/digest[:12]/'visual_review.json'
            p.atomic_json(review,dict(status='changes_required',shot_id='shot_test',output_sha256=digest))
            registry={'shot_test':dict(status='active_pending_quality_review',receipt=str(marker),output_sha256=digest)}
            base=dict(shot_id='shot_test',output='base.mkv',output_sha256='base',start_frame=10,end_frame=20,frames=10)
            with self.assertRaisesRegex(ValueError,'rejected'):
                d.apply_source_y_override(base,registry)
            # The decision binds the full digest, not merely the directory prefix.
            p.atomic_json(review,dict(status='changes_required',shot_id='shot_test',output_sha256='different'))
            self.assertEqual(d.apply_source_y_override(base,registry)['output_sha256'],digest)

    def test_endpoints_midpoint_and_y_bytes(self):
        self.assertIsNotNone(b)
        native = bytes([0,16,235,255, 50,60,70,80, 90,100,110,120])
        outgoing = np.array([10,20,30,40,50,60,70,80], dtype=np.uint8)
        incoming = np.array([110,120,130,140,150,160,170,180], dtype=np.uint8)
        for alpha, expected in [(0,outgoing),(.5,outgoing+50),(1,incoming)]:
            result = b.blend_uv(native, outgoing, incoming, alpha, 4)
            self.assertEqual(result[:4], native[:4])
            self.assertEqual(result[4:], expected.tobytes())
        with self.assertRaises(ValueError):
            b.blend_uv(native, outgoing, incoming, float('nan'), 4)

    def test_transition_requires_all_measured_frames_and_safe_anchors(self):
        self.assertIsNotNone(b)
        plan = dict(boundary_frame=10,support_start_frame=10,support_end_frame_exclusive=12,
            outgoing_anchor_frame=9,incoming_anchor_frames=[12,13,14],native_source_alpha=[
                dict(frame_global=10,alpha_incoming_for_review=.2),dict(frame_global=11,alpha_incoming_for_review=.8)])
        shot=dict(start_frame=10,end_frame=20)
        self.assertEqual(b.validate_transition(plan,shot),{10:.2,11:.8})
        plan['native_source_alpha'].pop()
        with self.assertRaisesRegex(ValueError,'measured'):
            b.validate_transition(plan,shot)

    def test_override_is_bound_to_base_and_full_verified_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'master.mkv'; output.write_bytes(b'lossless fixture')
            receipt = dict(status='draft_verified',exact_source_y=True,full_decode_verified=True,
                exact_outside_support_uv=True,base_output_sha256='base',output=str(output),output_sha256=p.sha256(output),
                shot_id='shot',start_frame=10,end_frame=20,frames=10,method='measured blend')
            marker = Path(tmp)/'treatment.json'; p.atomic_json(marker,receipt)
            registry={'shot':dict(receipt=str(marker),output_sha256=receipt['output_sha256'])}
            base=dict(shot_id='shot',output='base.mkv',output_sha256='base',start_frame=10,end_frame=20,frames=10)
            self.assertEqual(d.apply_source_y_override(base,registry)['output'],str(output))
            receipt.update(outgoing_shot_id='outgoing',outgoing_output_sha256='outgoing_hash')
            p.atomic_json(marker,receipt)
            with self.assertRaisesRegex(ValueError,'outgoing base'):
                d.apply_source_y_override(base,registry,{'outgoing':{'output_sha256':'changed'}})
            base['output_sha256']='changed'
            with self.assertRaisesRegex(ValueError,'base'):
                d.apply_source_y_override(base,registry)


if __name__=='__main__':
    unittest.main(verbosity=2)
