"""Portable planning/review invariants, with no GPU or external model required."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('portable_pipeline',Path(__file__).resolve().parents[1]/'pipeline.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


class PipelineTests(unittest.TestCase):
    def source(self,n=40):return dict(frame_count=n,fps_num=24,fps_den=1)
    def census(self):return dict(status='reviewed',reviewed_by='tester',reviewed_at='2026-10-07',shots=[
        dict(id='a',start_frame=0,end_frame=12,mode='passthrough'),
        dict(id='b',start_frame=12,end_frame=24,mode='passthrough'),
        dict(id='c',start_frame=24,end_frame=40,mode='passthrough')])
    def probe(self):return dict(streams=[dict(codec_type='video',pix_fmt='yuv420p',color_range='tv',color_space='smpte170m',
        field_order='progressive',start_time='0',r_frame_rate='24/1',avg_frame_rate='24/1',time_base='1/24',width=16,height=12),
        dict(codec_type='audio',start_time='0',sample_rate='48000',channels=2,time_base='1/48000')],frames=[dict(best_effort_timestamp=i) for i in range(40)])

    def test_whole_shot_continuity_nearest_boundary_and_long_shot(self):
        shots,batches=p.group_shots(self.census(),self.source(),1)
        self.assertEqual([b['shots'] for b in batches],[['a','b'],['c']])
        self.assertEqual([(b['start_frame'],b['end_frame']) for b in batches],[(0,24),(24,40)])
        c=self.census();c['shots']=[dict(id='long',start_frame=0,end_frame=40,mode='passthrough')]
        self.assertEqual(len(p.group_shots(c,self.source(),.1)[1]),1)

    def test_gap_overlap_negative_and_unreviewed_census_rejected(self):
        for start in [-1,11,13]:
            c=self.census();c['shots'][1]['start_frame']=start
            with self.assertRaises(ValueError):p.group_shots(c,self.source())
        c=self.census();c['status']='pending'
        with self.assertRaises(ValueError):p.group_shots(c,self.source())

    def test_source_contract_rejects_range_format_fps_start_and_vfr(self):
        self.assertEqual(p.validate_probe(self.probe())['frame_count'],40)
        for key,value in [('color_range','pc'),('pix_fmt','yuv420p10le'),('color_space','bt709'),('color_transfer','smpte2084'),('color_transfer','arib-std-b67'),('r_frame_rate','60/1'),('start_time','-1')]:
            probe=self.probe();probe['streams'][0][key]=value
            with self.assertRaises(ValueError):p.validate_probe(probe)
        probe=self.probe();probe['frames'][20]['best_effort_timestamp']=22
        with self.assertRaises(ValueError):p.validate_probe(probe)
        probe=self.probe();probe['frames'][0]['best_effort_timestamp']=1
        with self.assertRaises(ValueError):p.validate_probe(probe)
        probe=self.probe();probe['streams'][1]['start_time']='.1'
        with self.assertRaises(ValueError):p.validate_probe(probe)
        probe=self.probe()
        for f in probe['frames'][20:]:f['best_effort_timestamp']+=1
        with self.assertRaises(ValueError):p.validate_probe(probe)

    def fixture(self,root):
        source=root/'source.bin';source.write_bytes(b'original')
        census=root/'shots.json';p.atomic(census,self.census())
        project=root/'project'
        outputs=[json.dumps(self.probe()).encode(),json.dumps({'streams':self.probe()['streams']}).encode(),json.dumps({'frames':[dict(best_effort_timestamp=0,nb_samples=80000)]}).encode()]
        with patch.object(p.subprocess,'check_output',side_effect=outputs):p.init_project(source,census,project,1)
        return project,source,census

    def test_init_never_overwrites_existing_and_binds_source_census(self):
        with tempfile.TemporaryDirectory() as folder:
            project,source,census=self.fixture(Path(folder));state,_=p.load_project(project)
            self.assertEqual(p.next_batch(state)['id'],'batch_001')
            with self.assertRaises(ValueError):p.init_project(source,census,project)
            source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Stale source'):p.load_project(project)
            source.write_bytes(b'original');census.write_text('{}')
            with self.assertRaisesRegex(ValueError,'Stale shot census'):p.load_project(project)

    def test_stale_reference_and_pending_rejected_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            from PIL import Image
            root=Path(folder);ref=root/'ref.png';Image.new('RGB',(16,12),'gray').save(ref);marker=root/'ready.json'
            shot=dict(id='a',mode='colorize',start_frame=0,end_frame=10,references_ready=str(marker),_source=dict(sha256='test-source',width=16,height=12))
            self.assertEqual(p.reference_state(shot,root),'pending')
            record=dict(status='rejected');p.atomic(marker,record)
            self.assertEqual(p.reference_state(shot,root),'rejected')
            record=dict(status='approved',shot_id='a',source_sha256='test-source',approved_by='tester',approved_at='today',references=[dict(path=str(ref),sha256=p.digest(ref),source_frame=2,view='test',materials=['test'])])
            review=root/'review.json';p.atomic(review,dict(record,notes='Native review',geometry_checked=True,palette_checked=True,source_y_recombined_checked=True))
            record.update(review_path=str(review),review_sha256=p.digest(review))
            p.atomic(marker,record);self.assertEqual(p.reference_state(shot,root),'ready')
            ref.write_bytes(b'new guide')
            with self.assertRaisesRegex(ValueError,'Stale reference'):p.reference_state(shot,root)

    def test_review_pending_rejected_and_completed_next_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            project,_,_=self.fixture(Path(folder));state,_=p.load_project(project);batch=state['batches'][0]
            master=project/'draft.mkv';master.write_bytes(b'verified draft');receipt=project/'assembly.json';p.atomic(receipt,{'verified':True})
            batch.update(stage='delivered_pending_review',master=str(master),master_sha256=p.digest(master),assembly_receipt=str(receipt),assembly_receipt_sha256=p.digest(receipt))
            p.atomic(project/'pipeline.json',state)
            review=dict(status='pending',reviewed_by='tester',reviewed_at='today',notes='native check',master_sha256=p.digest(master))
            for status in ['pending','rejected']:
                review['status']=status;p.batch_review(project,'batch_001',review)
                self.assertEqual(p.next_batch(p.load_project(project)[0])['id'],'batch_001')
            review['status']='accepted';p.batch_review(project,'batch_001',review)
            self.assertEqual(p.next_batch(p.load_project(project)[0])['id'],'batch_002')
            frozen=p.digest(project/'pipeline.json');review['status']='rejected'
            with self.assertRaisesRegex(ValueError,'immutable'):p.batch_review(project,'batch_001',review)
            self.assertEqual(p.digest(project/'pipeline.json'),frozen)
            master.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Stale accepted'):p.load_project(project)

    def test_future_batch_never_launches(self):
        with tempfile.TemporaryDirectory() as folder:
            project,_,_=self.fixture(Path(folder))
            with patch.object(p.subprocess,'run') as run:
                with self.assertRaisesRegex(ValueError,'next unresolved'):p.execute(project,'batch_002','render')
                run.assert_not_called()

    def test_aac_priming_is_supported_only_when_decoded_clock_proves_zero_start(self):
        probe=self.probe();probe['streams'][1].update(codec_name='aac',start_time='-0.021333')
        with self.assertRaisesRegex(ValueError,'census'):p.validate_probe(probe)
        probe['audio_frames']=[dict(best_effort_timestamp=i*1024,nb_samples=1024) for i in range(3)]
        self.assertEqual(p.validate_probe(probe)['audio_sample_rate'],48000)
        probe['audio_frames'][0]['best_effort_timestamp']=-1024
        with self.assertRaisesRegex(ValueError,'sample clock'):p.validate_probe(probe)
        probe['audio_frames']=[dict(best_effort_timestamp=0,nb_samples=1024),dict(best_effort_timestamp=1,nb_samples=1024)]
        probe['streams'][1]['time_base']='1/1'
        with self.assertRaisesRegex(ValueError,'sample clock'):p.validate_probe(probe)

    def test_revision_preserves_prior_review_and_requires_versioned_render(self):
        with tempfile.TemporaryDirectory() as folder:
            project,_,_=self.fixture(Path(folder));state,_=p.load_project(project)
            state['batches'][0].update(review='rejected',quality_review={'status':'rejected','notes':'leakage'},stage='delivered_pending_review')
            p.atomic(project/'pipeline.json',state)
            revised=p.revise_batch(project,'batch_001','Correct the leakage')
            self.assertEqual(revised['revisions'][0]['prior_state']['quality_review']['notes'],'leakage')
            with self.assertRaisesRegex(ValueError,'render new'):p.execute(project,'batch_001','deliver')
            with patch.object(p.subprocess,'run') as run:p.execute(project,'batch_001','render')
            command=run.call_args.args[0];self.assertIn('--rerender',command);self.assertIn('Correct the leakage',command)
            self.assertTrue(p.load_project(project)[0]['batches'][0]['force_rerender'])
            with self.assertRaises(ValueError):p.revise_batch(project,'batch_002','Future revision denied')

    def test_full_assembly_requires_accepted_batches_and_retains_pending_final_review(self):
        with tempfile.TemporaryDirectory() as folder:
            project,_,_=self.fixture(Path(folder))
            with patch.object(p.subprocess,'run') as run:
                with self.assertRaisesRegex(ValueError,'All batches'):p.assemble(project)
                run.assert_not_called()
            state,_=p.load_project(project);rows=[]
            for b in state['batches']:
                master=project/(b['id']+'.mkv');master.write_bytes(b['id'].encode())
                receipt=project/(b['id']+'.json');shots=[dict(shot_id=s,output_sha256='selected-'+s) for s in b['shots']];rows.extend(shots)
                p.atomic(receipt,dict(shots=shots))
                b.update(review='accepted',master=str(master),master_sha256=p.digest(master),assembly_receipt=str(receipt),assembly_receipt_sha256=p.digest(receipt),
                         quality_review=dict(status='accepted',master_sha256=p.digest(master)))
            p.atomic(project/'pipeline.json',state)
            full=project/'full';full.mkdir();master=full/'master.mkv';master.write_bytes(b'full assembled')
            result=dict(status='draft_verified_pending_visual_review',exact_source_y=True,exact_source_pcm=True,full_decode_verified=True,
                shots=rows,master=str(master),master_sha256=p.digest(master),preview='preview.mp4',preview_sha256='preview')
            p.atomic(full/'assembly.json',result);p.atomic(project/'engine/full_delivery_status.json',dict(stage='draft_scope_ready',assembly=result))
            with patch.object(p.subprocess,'run') as run:artifact=p.assemble(project)
            self.assertIn('--full',run.call_args.args[0]);self.assertIn('--scope',run.call_args.args[0])
            self.assertFalse(artifact['automatically_accepted']);self.assertIn('pending',artifact['status'])
            frozen=p.digest(project/'pipeline.json')
            review=dict(status='rejected',reviewed_by='tester',reviewed_at='today',notes='Cannot mutate accepted work',master_sha256=state['batches'][0]['master_sha256'])
            with self.assertRaisesRegex(ValueError,'immutable'):p.batch_review(project,'batch_001',review)
            self.assertEqual(p.digest(project/'pipeline.json'),frozen)
            with self.assertRaises(ValueError):p.revise_batch(project,'batch_001','Cannot revise accepted earlier work')

    def test_source_bound_reference_review_and_native_size_are_consumed(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=root/'ref.png';Image.new('RGB',(16,12),'gray').save(image)
            source=dict(sha256='source',width=16,height=12)
            shot=dict(id='s',mode='colorize',start_frame=0,end_frame=1,references_ready=str(root/'ready.json'))
            row=dict(path=str(image),sha256=p.digest(image),source_frame=0,view='synthetic',materials=['synthetic'])
            review=dict(status='approved',shot_id='s',source_sha256='source',approved_by='human',approved_at='now',notes='Viewed native guide',
                geometry_checked=True,palette_checked=True,source_y_recombined_checked=True,references=[row])
            review_path=root/'review.json';p.atomic(review_path,review)
            marker=dict(review,schema_version=1,review_path=str(review_path),review_sha256=p.digest(review_path));p.atomic(root/'ready.json',marker)
            self.assertEqual(p.reference_state(shot,root,source),'ready')
            with self.assertRaisesRegex(ValueError,'current source'):p.reference_state(shot,root,dict(source,sha256='changed-source'))
            review['palette_checked']=False;p.atomic(review_path,review)
            with self.assertRaisesRegex(ValueError,'changed'):p.reference_state(shot,root,source)
            marker['review_sha256']=p.digest(review_path);p.atomic(root/'ready.json',marker)
            with self.assertRaisesRegex(ValueError,'visual checks'):p.reference_state(shot,root,source)


if __name__=='__main__':unittest.main()
