import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
"""Safety and resume checks; these never load a model or run a GPU job."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1] / 'engine/production.py'
engine = None
if ENGINE.exists():
    spec = importlib.util.spec_from_file_location('production', ENGINE)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(engine, 'The resumable production engine must exist')
        self.tmp = tempfile.TemporaryDirectory(dir=ENGINE.parent)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / 'source.mkv'
        self.source.write_bytes(b'native-source')
        self.doc = {'schema_version': 1, 'source': {'path': str(self.source),
            'frame_count': 80000, 'fps_num': 24000, 'fps_den': 1001,
            'width': 960, 'height': 720, 'pixel_format': 'yuv420p'},
            'shots': [{'id': 'title', 'start_frame': 0, 'end_frame': 120,
                'mode': 'passthrough', 'batch_id': 'b1'},
                {'id': 'lecture', 'start_frame': 120, 'end_frame': 80000,
                'mode': 'colorize', 'batch_id': 'b2'}]}

    def test_full_lecture_arbitrary_length_and_gaps(self):
        result = engine.validate_manifest(self.doc)
        self.assertEqual(result['shots'][-1]['frames'], 79880)
        broken = copy.deepcopy(self.doc)
        broken['shots'][1]['start_frame'] = 121
        with self.assertRaisesRegex(ValueError, 'contiguous'):
            engine.validate_manifest(broken)
        broken = copy.deepcopy(self.doc)
        broken['source']['frame_count'] = 80001
        with self.assertRaisesRegex(ValueError, 'coverage'):
            engine.validate_manifest(broken)

    def test_reference_approval_is_local_and_hash_bound(self):
        shot = engine.validate_manifest(self.doc)['shots'][1]
        ref = self.base / 'guide.png'
        from PIL import Image
        Image.new('RGB',(960,720),'gray').save(ref)
        marker = self.base / 'ready.json'
        shot['references_ready'] = str(marker)
        self.assertIsNone(engine.approved_references(shot))
        data = {'schema_version': 1, 'shot_id': 'lecture', 'status': 'pending',
            'approved_by': 'reviewer', 'approved_at': '2026-10-07T00:00:00Z',
            'references': [{'path': str(ref), 'sha256': engine.sha256(ref),
                'source_frame': 150, 'view': 'lecturer close view',
                'materials': ['skin', 'suit', 'board']} ]}
        engine.atomic_json(marker, data)
        self.assertIsNone(engine.approved_references(shot))
        data['status'] = 'approved'
        data['source_sha256'] = shot['_source']['sha256']
        review_path = self.base/'review.json'
        engine.atomic_json(review_path,dict(data,notes='Native guides reviewed',geometry_checked=True,palette_checked=True,source_y_recombined_checked=True))
        data.update(review_path=str(review_path),review_sha256=engine.sha256(review_path))
        engine.atomic_json(marker, data)
        self.assertEqual(engine.approved_references(shot)['references'][0]['local_frame'], 30)
        ref.write_bytes(b'changed-colors')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            engine.approved_references(shot)
        data['references'][0]['sha256'] = engine.sha256(ref)
        data['references'][0]['source_frame'] = 119
        engine.atomic_json(marker, data)
        with self.assertRaisesRegex(ValueError, 'outside'):
            engine.approved_references(shot)

    def test_audited_prefix_requires_explicit_contiguous_pending_tail(self):
        self.doc['shots'] = self.doc['shots'][:1]
        self.doc['pending_ranges'] = [{'start_frame': 120, 'end_frame': 80000, 'reason': 'Cut audit pending'}]
        result = engine.validate_manifest(self.doc)
        self.assertEqual(result['pending_ranges'][0]['start_frame'], 120)
        self.doc['pending_ranges'][0]['start_frame'] = 121
        with self.assertRaisesRegex(ValueError, 'contiguous'):
            engine.validate_manifest(self.doc)

    def test_resume_rejects_missing_changed_and_different_configuration(self):
        output = self.base / 'prediction.mkv'
        output.write_bytes(b'verified-prediction')
        attempt = {'status': 'pending_quality_review', 'fingerprint': 'same',
            'output': str(output), 'output_sha256': engine.sha256(output),
            'full_decode_verified': True, 'verified_decoded_frames': 42, 'frames': 42}
        self.assertTrue(engine.reusable_attempt(attempt, 'same'))
        self.assertFalse(engine.reusable_attempt(attempt, 'different'))
        output.write_bytes(b'altered')
        self.assertFalse(engine.reusable_attempt(attempt, 'same'))
        output.unlink()
        self.assertFalse(engine.reusable_attempt(attempt, 'same'))

    def test_single_worker_lock_and_atomic_state(self):
        lock = self.base / 'gpu.lock'
        with engine.ExclusiveLock(lock):
            with self.assertRaisesRegex(RuntimeError, 'worker'):
                with engine.ExclusiveLock(lock):
                    self.fail('Two workers acquired the lock')
        with engine.ExclusiveLock(lock):
            pass
        target = self.base / 'status.json'
        engine.atomic_json(target, {'stage': 'waiting'})
        engine.atomic_json(target, {'stage': 'complete'})
        self.assertEqual(json.loads(target.read_text())['stage'], 'complete')
        self.assertEqual(list(self.base.glob('*.tmp')), [])

    def test_windows_wddm_desktop_apps_are_not_competing_render_jobs(self):
        self.assertTrue(hasattr(engine, 'gpu_compute_conflicts'), 'WDDM-aware GPU process classification is required')
        output = '12624, C:\\Windows\\explorer.exe\n98936, C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\n44, C:\\env\\python.exe\n'
        self.assertEqual(engine.gpu_compute_conflicts(output, windows=True), ['44, C:\\env\\python.exe'])
        self.assertEqual(engine.gpu_compute_conflicts('8, /usr/bin/python3\n', windows=False), ['8, /usr/bin/python3'])

    def test_master_reuse_requires_exact_source_y_and_asset_proof(self):
        shot = self.doc['shots'][1]
        shot['mode'] = 'reusable_approved_master'
        shot['source_asset'] = {'path': str(self.source)}
        marker = self.base / 'reuse.json'
        shot['reuse_ready'] = str(marker)
        try:
            shot = engine.validate_manifest(self.doc)['shots'][1]
        except ValueError as error:
            self.fail(f'Explicit approved-master reuse mode is required: {error}')
        self.assertIsNone(engine.approved_references(shot))
        proof = {'schema_version': 1, 'status': 'approved', 'shot_id': 'lecture',
            'start_frame': 120, 'end_frame': 80000, 'frames': 79880,
            'asset_path': str(self.source), 'asset_sha256': engine.sha256(self.source),
            'source_sha256': 'source-sha', 'source_y_sha256': 'y-sha', 'asset_y_sha256': 'y-sha',
            'exact_decoded_y': True, 'approved_by': 'reviewer', 'approved_at': '2026-10-07'}
        engine.atomic_json(marker, proof)
        self.assertEqual(engine.approved_references(shot)['reuse']['asset_sha256'], engine.sha256(self.source))
        proof['asset_y_sha256'] = 'wrong-y'
        engine.atomic_json(marker, proof)
        with self.assertRaisesRegex(ValueError, 'luminance'):
            engine.approved_references(shot)

    def test_incidental_reuse_approval_timestamp_does_not_change_fingerprint(self):
        shot = engine.validate_manifest(self.doc)['shots'][1]
        shot['mode'] = 'reusable_approved_master'
        approval = {'references': [], 'reuse': {'asset_sha256': 'asset', 'source_sha256': 'source',
            'source_y_sha256': 'y', 'asset_y_sha256': 'y', 'approved_at': 'old'}}
        first = engine.fingerprint(shot, {'sha256': 'source'}, {'digest': 'model'}, approval)
        approval['reuse']['approved_at'] = 'new'
        self.assertEqual(first, engine.fingerprint(shot, {'sha256': 'source'}, {'digest': 'model'}, approval))

    def test_quality_acceptance_binds_verified_output_hash(self):
        self.assertTrue(hasattr(engine, 'apply_quality_review'), 'Explicit quality review transition is required')
        output = self.base / 'output.mkv'
        output.write_bytes(b'verified-prediction')
        attempt_path = self.base / 'attempt.json'
        record = {'shot_id': 'lecture', 'attempt': 1, 'status': 'pending_quality_review',
            'output': str(output), 'output_sha256': engine.sha256(output), 'full_decode_verified': True}
        engine.atomic_json(attempt_path, record)
        review = {'shot_id': 'lecture', 'attempt': 1, 'status': 'accepted',
            'output_sha256': 'wrong', 'reviewed_by': 'reviewer', 'reviewed_at': 'today', 'notes': 'Native source-Y previews reviewed'}
        with self.assertRaisesRegex(ValueError, 'hash'):
            engine.apply_quality_review(attempt_path, review)
        review['output_sha256'] = record['output_sha256']
        engine.apply_quality_review(attempt_path, review)
        self.assertEqual(engine.read_json(attempt_path)['status'], 'accepted')

    def test_wait_queue_exits_when_all_selected_outputs_are_completed(self):
        document = engine.validate_manifest(self.doc)
        shot = document['shots'][0]
        identity, runtime = {'sha256': 'source'}, {'digest': 'runtime'}
        approval = engine.approved_references(shot)
        output = self.base/'complete.mkv'
        output.write_bytes(b'previously-stream-verified-output')
        prior = {'shot_id': shot['id'], 'attempt': 1, 'status': 'pending_quality_review',
            'fingerprint': engine.fingerprint(shot, identity, runtime, approval),
            'output': str(output), 'output_sha256': engine.sha256(output), 'frames': shot['frames'],
            'verified_decoded_frames': shot['frames'], 'full_decode_verified': True}
        stages = []
        args = SimpleNamespace(wait=True, rerender=False, max_shots=None, reason=None)
        with patch.object(engine, 'HERE', self.base), patch.object(engine, 'STOP', self.base/'STOP.json'), \
                patch.object(engine, 'source_identity', return_value=identity), \
                patch.object(engine, 'runtime_identity', return_value=runtime), \
                patch.object(engine, 'all_attempts', return_value=[prior]), \
                patch.object(engine, 'publish', side_effect=lambda doc, selected, stage, *a, **k: stages.append(stage)), \
                patch.object(engine, 'run_attempt', side_effect=AssertionError('Completed output must not rerender')), \
                patch.object(engine.time, 'sleep', side_effect=AssertionError('--wait must exit after completion')):
            engine.run_queue(args, document, {shot['id']})
        self.assertEqual(stages[-1], 'queue_complete')
        # A second worker can acquire the same lock immediately after return.
        with engine.ExclusiveLock(self.base/'gpu_queue.lock'):
            pass

    def test_atomic_checkpoint_retries_transient_rename_denial(self):
        target = self.base/'checkpoint.json'
        engine.atomic_json(target, {'stage': 'old'})
        real_replace = os.replace
        failures = [PermissionError(5, 'Sharing race'), PermissionError(5, 'Sharing race')]
        def replace_with_two_readers(source, destination):
            if failures:
                raise failures.pop()
            return real_replace(source, destination)
        with patch.object(engine.os, 'replace', side_effect=replace_with_two_readers) as replace, \
                patch.object(engine.time, 'sleep'):
            engine.atomic_json(target, {'stage': 'complete'})
        self.assertEqual(replace.call_count, 3)
        self.assertEqual(engine.read_json(target), {'stage': 'complete'})

    def test_atomic_checkpoint_denial_has_bounded_retries_and_keeps_evidence(self):
        target = self.base/'checkpoint.json'
        engine.atomic_json(target, {'stage': 'old'})
        with patch.object(engine.os, 'replace', side_effect=PermissionError(5, 'Persistent denial')) as replace, \
                patch.object(engine.time, 'sleep'):
            with self.assertRaises(PermissionError):
                engine.atomic_json(target, {'stage': 'complete'})
        self.assertEqual(replace.call_count, 20)
        self.assertEqual(engine.read_json(target), {'stage': 'old'})
        evidence = list(self.base.glob('checkpoint.json.*.tmp'))
        self.assertEqual(len(evidence), 1)
        self.assertEqual(engine.read_json(evidence[0]), {'stage': 'complete'})

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics only')
    def test_real_windows_reader_without_delete_share_is_retried(self):
        import ctypes
        from ctypes import wintypes
        import threading
        target = self.base/'windows_checkpoint.json'
        engine.atomic_json(target, {'stage': 'old'})
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(target), 0x80000000, 3, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        release = threading.Timer(.15, lambda: kernel.CloseHandle(handle))
        errors = []
        real_replace = os.replace
        def observed_replace(source, destination):
            try:
                return real_replace(source, destination)
            except PermissionError as error:
                errors.append(error.winerror)
                raise
        release.start()
        try:
            with patch.object(engine.os, 'replace', side_effect=observed_replace):
                engine.atomic_json(target, {'stage': 'complete'})
        finally:
            release.join()
        self.assertTrue(errors, 'An actual Windows sharing denial must have been exercised')
        self.assertEqual(engine.read_json(target), {'stage': 'complete'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
