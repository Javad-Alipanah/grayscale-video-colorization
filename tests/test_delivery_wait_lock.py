import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
"""An incomplete future batch must not monopolize the delivery assembly lock."""
import argparse
from pathlib import Path
from unittest import TestCase,main,mock
import production as p
import delivery as d

class DeliveryWaitLockTest(TestCase):
    def test_rejected_review_waits_and_releases_shared_delivery_lock(self):
        held=[];updates=[]
        class Lock:
            def __init__(self,*args,**kwargs):pass
            def __enter__(self):held.append(True)
            def __exit__(self,*args):held.pop()
        document=dict(source=dict(frame_count=1),shots=[dict(id='one',batch_id='batch_05',frames=1,mode='passthrough')])
        attempt=dict(attempt=1,output_sha256='base')
        base=dict(shot_id='one',frames=1,output='fixture.mkv',output_sha256='base')
        args=argparse.Namespace(manifest=Path('fixture.json'),batch='batch_05',wait=True,wait_for_queue=True,status_path=None)
        def sleep(_):
            self.assertFalse(held,'A visual rejection must not monopolize the delivery lock')
            self.assertEqual(updates[-1]['stage'],'waiting_for_corrected_quality_review')
            raise InterruptedError('End held review polling cycle')
        with mock.patch.object(p,'read_json',return_value=document),mock.patch.object(p,'validate_manifest',side_effect=lambda x:x), \
                mock.patch.object(p,'source_identity',return_value={}),mock.patch.object(p,'runtime_identity',return_value={}), \
                mock.patch.object(p,'ExclusiveLock',Lock),mock.patch.object(p,'atomic_json',side_effect=lambda path,state:updates.append(dict(state))), \
                mock.patch.object(d,'choose_attempt',return_value=attempt),mock.patch.object(d.sm,'load',return_value=None), \
                mock.patch.object(d,'reviewed_reclaimed_base',return_value=base),mock.patch.object(d,'override_base_context',return_value={}), \
                mock.patch.object(d,'apply_source_y_override',side_effect=p.QualityReviewRejected('Exact native review rejected')), \
                mock.patch.object(d,'assemble_scope') as assemble,mock.patch.object(d.time,'sleep',side_effect=sleep):
            with self.assertRaises(InterruptedError):d.watch(args)
            assemble.assert_not_called()

    def test_waiting_for_predictions_releases_shared_delivery_lock(self):
        held=[]
        class Lock:
            def __init__(self,*args,**kwargs):pass
            def __enter__(self):held.append(True)
            def __exit__(self,*args):held.pop()
        document=dict(source=dict(frame_count=1),shots=[dict(id='one',batch_id='batch_03',frames=1,mode='passthrough')])
        args=argparse.Namespace(manifest=Path('fixture.json'),batch='batch_03',wait=True,wait_for_queue=True,status_path=None)
        def sleep(_):
            self.assertFalse(held,'Waiting for future predictions must release the CPU delivery lock')
            raise InterruptedError('End one polling cycle')
        with mock.patch.object(p,'read_json',return_value=document),mock.patch.object(p,'validate_manifest',side_effect=lambda x:x), \
                mock.patch.object(p,'source_identity',return_value={}),mock.patch.object(p,'runtime_identity',return_value={}), \
                mock.patch.object(p,'ExclusiveLock',Lock),mock.patch.object(p,'atomic_json'), \
                mock.patch.object(d,'choose_attempt',return_value=None),mock.patch.object(d.time,'sleep',side_effect=sleep):
            with self.assertRaises(InterruptedError):d.watch(args)

if __name__=='__main__':main(verbosity=2)
