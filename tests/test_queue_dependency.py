import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
"""A released per-job lock must not bypass the remaining correction contexts."""
import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase,main,mock
import production as p
import queue_after_plan as q

class DependencyTest(TestCase):
    def test_complete_plan_required_before_start_and_disk_guard_rechecked(self):
        args=argparse.Namespace(manifest=Path('manifest'),dependency_plan=Path('plan'),storage_forecast=Path('forecast'),status_path=Path('status'),batch='batch_03')
        stages=iter(['authorized_correction_queue','authorized_correction_queue','overlap_inference_complete'])
        def read(path):
            if path==args.manifest:return {'shots':[{'id':'one','batch_id':'batch_03'}]}
            if path==args.dependency_plan:return {'status':next(stages)}
            return {'required_free_at_gpu_start_gib':36}
        with mock.patch.object(p,'read_json',side_effect=read),mock.patch.object(p,'validate_manifest',side_effect=lambda x:x), \
                mock.patch.object(p,'publish') as publish,mock.patch.object(p,'run_queue') as run, \
                mock.patch.object(q.shutil,'disk_usage',return_value=SimpleNamespace(free=50*2**30)), \
                mock.patch.object(q.time,'sleep',side_effect=lambda _:self.assertFalse(run.called)):
            q.main(args)
            self.assertEqual(publish.call_count,2)
            run.assert_called_once()
        stages=iter(['overlap_inference_complete'])
        with mock.patch.object(p,'read_json',side_effect=read),mock.patch.object(p,'validate_manifest',side_effect=lambda x:x), \
                mock.patch.object(p,'publish'),mock.patch.object(p,'run_queue') as run, \
                mock.patch.object(q.shutil,'disk_usage',return_value=SimpleNamespace(free=20*2**30)):
            with self.assertRaisesRegex(RuntimeError,'disk budget'):q.main(args)
            run.assert_not_called()

if __name__=='__main__':main(verbosity=2)
