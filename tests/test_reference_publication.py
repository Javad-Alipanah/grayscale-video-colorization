import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
"""Incomplete approval publication must wait without admitting changed guides."""
import argparse
from pathlib import Path
import tempfile
from unittest import TestCase, main, mock
import production as p
import delivery as d


class PublicationTests(TestCase):
    def test_changed_guide_is_explicitly_pending_and_never_approved(self):
        with tempfile.TemporaryDirectory(dir=p.HERE) as directory:
            directory=Path(directory); guide=directory/'guide.png'; marker=directory/'ready.json'
            guide.write_bytes(b'approved')
            approval=dict(schema_version=1,shot_id='shot',status='approved',approved_by='reviewer',approved_at='now',
                references=[dict(path=str(guide),sha256=p.sha256(guide),source_frame=0,view='wide',materials=['board'])])
            p.atomic_json(marker,approval);guide.write_bytes(b'new publication')
            shot=dict(id='shot',mode='colorize',start_frame=0,end_frame=1,references_ready=str(marker))
            with self.assertRaises(p.ReferencePublicationPending):p.approved_references(shot)
            from PIL import Image
            Image.new('RGB',(16,12),'gray').save(guide)
            approval['references'][0]['sha256']=p.sha256(guide)
            shot['_source']=dict(sha256='test-source',width=16,height=12)
            approval['source_sha256']='test-source';review=directory/'review.json'
            p.atomic_json(review,dict(approval,notes='Reviewed native guide',geometry_checked=True,palette_checked=True,source_y_recombined_checked=True))
            approval.update(review_path=str(review),review_sha256=p.sha256(review));p.atomic_json(marker,approval)
            self.assertEqual(len(p.approved_references(shot)['references']),1)

    def test_delivery_waits_without_swallowing_nonpublication_errors(self):
        document=dict(source=dict(frame_count=1),shots=[dict(id='shot',batch_id='batch',frames=1,mode='passthrough')])
        args=argparse.Namespace(manifest=Path('fixture'),batch='batch',wait=True,wait_for_queue=True,status_path=None)
        updates=[]
        common=[mock.patch.object(p,'read_json',return_value=document),mock.patch.object(p,'validate_manifest',side_effect=lambda x:x),
            mock.patch.object(p,'source_identity',return_value={}),mock.patch.object(p,'runtime_identity',return_value={}),
            mock.patch.object(p,'ExclusiveLock'),mock.patch.object(p,'atomic_json',side_effect=lambda path,state:updates.append(dict(state)))]
        from contextlib import ExitStack
        with ExitStack() as stack:
            for context in common:stack.enter_context(context)
            with mock.patch.object(d,'choose_attempt',side_effect=p.ReferencePublicationPending('changed guide')), \
                    mock.patch.object(d.time,'sleep',side_effect=InterruptedError('end polling')):
                with self.assertRaises(InterruptedError):d.watch(args)
            self.assertEqual(updates[-1]['reference_publication_pending'],{'shot':'changed guide'})
            with mock.patch.object(d,'choose_attempt',side_effect=ValueError('bad correction provenance')):
                with self.assertRaisesRegex(ValueError,'bad correction provenance'):d.watch(args)

    def test_gpu_queue_retries_publication_before_rendering(self):
        shot=dict(id='shot',mode='colorize',batch_id='batch')
        document=dict(source={},shots=[shot])
        args=argparse.Namespace(wait=True,wait_for_queue=True,rerender=False,max_shots=None,reason='test')
        calls=[]
        with mock.patch.object(p,'ExclusiveLock'),mock.patch.object(p,'publish') as publish, \
                mock.patch.object(p,'source_identity',return_value={}),mock.patch.object(p,'runtime_identity',return_value={}), \
                mock.patch.object(p,'all_attempts',return_value=[]),mock.patch.object(p,'fingerprint',return_value='fingerprint'), \
                mock.patch.object(p,'approved_references',side_effect=[p.ReferencePublicationPending('changed guide'),{}]), \
                mock.patch.object(p,'prepare_batch',return_value={}), \
                mock.patch.object(p.time,'sleep',side_effect=lambda _:calls.append('wait')), \
                mock.patch.object(p,'run_attempt',side_effect=lambda *a:calls.append('render')):
            p.run_queue(args,document,{'shot'})
        self.assertEqual(calls,['wait','render'])
        self.assertTrue(any('changed guide' in str(call) for call in publish.call_args_list))


if __name__=='__main__':main(verbosity=2)
