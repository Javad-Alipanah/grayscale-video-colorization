import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "engine"))
from config import PROJECT as _PROJECT
(_PROJECT / "engine").mkdir(parents=True, exist_ok=True)
"""Native source UV follows a moving photo matte and excludes foreground."""
import hashlib
import argparse
from pathlib import Path
import subprocess
import tempfile
from unittest import TestCase,main,mock
import production as p
import delivery as d
import scientific_mask as sm


class ScientificMaskTests(TestCase):
    def test_analytic_photo_exit_uses_each_original_uv_frame_and_refuses_partial_mask(self):
        import apply_neutral_photo_exit as photo
        with tempfile.TemporaryDirectory(dir=p.HERE) as temporary:
            root=Path(temporary);pixels=256
            def encode(name,frames,fmt):
                path=root/(name+'.mkv')
                subprocess.run([str(p.FFMPEG),'-v','error','-y','-f','rawvideo','-pix_fmt',fmt,'-s','16x16','-framerate','24',
                    '-i','pipe:0','-an','-c:v','ffv1','-level','3',str(path)],input=b''.join(frames),check=True)
                return path
            frames=[bytes([40+i]*pixels+[112+i]*pixels+[140-i]*pixels) for i in range(5)]
            source=encode('source',frames,'yuv444p');mask=encode('mask',[bytes([255]*pixels)]*5,'gray')
            meta=dict(width=16,height=16,fps_num=24,fps_den=1)
            scene=dict(id='photo',start_frame=20,end_frame=21,frames=1)
            transition=dict(support_start_frame=21,support_end_frame_exclusive=24)
            identity=dict(sha256='native-source');clip=dict(path=str(source),sha256=p.sha256(source),source_sha256='native-source',source_clip_start_frame=20,source_clip_end_frame=25)
            config=dict(path=mask,marker=root/'ready.json',content_digest='all_photo',record=dict(start_frame=20,mask_sha256=p.sha256(mask)))
            with mock.patch.object(p,'RENDER',root/'render'),mock.patch.object(sm,'load',return_value=config),mock.patch.object(photo,'update'):
                result=photo.source_uv_handle(dict(source=meta),scene,transition,dict(source_clip=clip),identity)
                raw=subprocess.check_output([str(p.FFMPEG),'-v','error','-i',result['output'],'-f','rawvideo','-pix_fmt','yuv444p','pipe:1'])
                self.assertEqual(raw,b''.join(frames[1:4]))
                self.assertTrue(result['exact_original_source_uv'])
                bad=encode('partial_mask',[bytes([0]+[255]*(pixels-1))]*5,'gray')
                config.update(path=bad,content_digest='partial_photo');config['record']['mask_sha256']=p.sha256(bad)
                with self.assertRaisesRegex(ValueError,'unmasked pixels'):
                    photo.source_uv_handle(dict(source=meta),scene,transition,dict(source_clip=clip),identity)
                canonical=dict(scene,mode='passthrough')
                neutral=photo.source_uv_handle(dict(source=meta,shots=[canonical]),canonical,transition,dict(source_clip=clip),identity)
                self.assertTrue(neutral['canonical_passthrough_verified'])
                self.assertFalse(neutral['whole_photo_mask_verified'])
                self.assertEqual(neutral['source_yuv_sha256'],result['source_yuv_sha256'])
                with self.assertRaisesRegex(ValueError,'frozen canonical scene'):
                    photo.source_uv_handle(dict(source=meta,shots=[scene]),canonical,transition,dict(source_clip=clip),identity)

    def test_scientific_scope_waits_for_hash_bound_composite_review(self):
        with tempfile.TemporaryDirectory(dir=p.HERE) as temporary, mock.patch.object(p,'PROJECT',Path(temporary)):
            shot=dict(id='photo',scientific_screen_scene_id='photo')
            merges={'photo':dict(output_sha256='current')}
            self.assertIsNotNone(d.scientific_scope_hold('batch',[shot],merges,dict(sha256='source')))
            marker=Path(temporary)/'scenes/qc/projection_masks/batch_delivery_ready.json'
            p.atomic_json(marker,dict(status='scientific_scope_review_pass',source_sha256='source',
                selected_output_sha256={'photo':'old'},scene_hypothesis_masks_reviewed=True,source_dissolve_composites_reviewed=True))
            self.assertIsNotNone(d.scientific_scope_hold('batch',[shot],merges,dict(sha256='source')))
            ready=p.read_json(marker);ready['selected_output_sha256']={'photo':'current'};p.atomic_json(marker,ready)
            self.assertIsNone(d.scientific_scope_hold('batch',[shot],merges,dict(sha256='source')))
            self.assertIsNone(d.scientific_scope_hold('batch',[dict(id='ordinary')],merges,dict(sha256='source')))

    def test_trial_mask_cannot_enter_protected_delivery(self):
        with tempfile.TemporaryDirectory(dir=p.HERE) as temporary:
            marker=Path(temporary)/'mask_ready.json'
            p.atomic_json(marker,dict(status='source_mask_trial_ready'))
            shot=dict(mode='colorize',scientific_screen_scene_id='photo',scientific_screen_mask_ready=str(marker))
            with self.assertRaisesRegex(sm.ScientificMaskPending,'native review'):
                sm.load(shot,{}, {})

    def test_real_lossless_mask_uses_global_positions_and_preserves_foreground(self):
        with tempfile.TemporaryDirectory(dir=p.HERE) as temporary:
            root=Path(temporary);pixels=256
            def encode(name,frames,pix_fmt):
                path=root/(name+'.mkv')
                subprocess.run([str(p.FFMPEG),'-v','error','-y','-f','rawvideo','-pix_fmt',pix_fmt,'-s','16x16','-framerate','24',
                    '-i','pipe:0','-an','-c:v','ffv1','-level','3',str(path)],input=b''.join(frames),check=True)
                return path
            source_frames=[bytes([30+i]*pixels+[120+i]*pixels+[135+i]*pixels) for i in range(5)]
            source=encode('source',source_frames,'yuv444p')
            base_frames=[source_frames[i][:pixels]+bytes([80]*pixels+[190]*pixels) for i in range(1,4)]
            base_path=encode('base',base_frames,'yuv444p')
            mattes=[bytes([0]*pixels),bytes([255,0,0,0,255,0,0,0])*32,bytes([0,255,0,0,0,0,255,0])*32,bytes([255]*pixels),bytes([0]*pixels)]
            mask=encode('mask',mattes,'gray');marker=root/'mask_ready.json'
            source_meta=dict(width=16,height=16,fps_num=24,fps_den=1)
            p.atomic_json(marker,dict(schema_version=1,status='source_mask_trial_ready',scene_id='photo',source_sha256='source',
                **source_meta,start_frame=10,end_frame=15,mask_path=str(mask),mask_sha256=p.sha256(mask),pixel_format='gray',foreground_exclusions_included=True))
            shot=dict(id='overlap_photo',mode='colorize',start_frame=11,end_frame=14,frames=3,
                scientific_screen_scene_id='photo',scientific_screen_mask_ready=str(marker))
            base=dict(shot_id=shot['id'],status='draft_verified',exact_source_y=True,full_decode_verified=True,frames=3,start_frame=11,end_frame=14,
                output=str(base_path),output_sha256=p.sha256(base_path),source_y=dict(sha256=hashlib.sha256(b''.join(f[:pixels] for f in base_frames)).hexdigest()))
            attempt=dict(source_clip=dict(path=str(source),source_clip_start_frame=10,source_clip_end_frame=15,source_sha256='source',sha256=p.sha256(source)))
            identity=dict(sha256='source',path=str(source))
            config=sm.load(shot,source_meta,identity,allow_trial=True)
            with mock.patch.object(d,'BASE',root/'delivery'):
                result=sm.apply(dict(source=source_meta),shot,attempt,base,identity,config,lambda **x:None)
                # Rolling cleanup may prune reproducible media while retaining
                # its provenance receipt; that must be a cache miss, not a crash.
                Path(result['output']).unlink()
                rebuilt=sm.apply(dict(source=source_meta),shot,attempt,base,identity,config,lambda **x:None)
                self.assertEqual(rebuilt['decoded_yuv_sha256'],result['decoded_yuv_sha256'])
            raw=subprocess.check_output([str(p.FFMPEG),'-v','error','-i',result['output'],'-f','rawvideo','-pix_fmt','yuv444p','pipe:1'])
            for local in range(3):
                frame=raw[local*3*pixels:(local+1)*3*pixels];original=source_frames[local+1];before=base_frames[local];matte=mattes[local+1]
                self.assertEqual(frame[:pixels],original[:pixels])
                for pixel in range(pixels):
                    for offset in (pixels,2*pixels):self.assertEqual(frame[offset+pixel],original[offset+pixel] if matte[pixel] else before[offset+pixel])
            self.assertEqual(result['full_source_uv_passthrough_frames_global'],[13])
            self.assertTrue(result['exact_source_y']);self.assertTrue(result['exact_source_uv_inside_mask']);self.assertTrue(result['exact_prediction_uv_outside_mask'])

    def test_missing_mask_holds_delivery_without_affecting_ordinary_shots(self):
        self.assertIsNone(sm.load(dict(mode='colorize'),{},{}))
        with tempfile.TemporaryDirectory(dir=p.HERE) as temporary:
            with self.assertRaises(sm.ScientificMaskPending):
                sm.load(dict(mode='colorize',scientific_screen_scene_id='scene',scientific_screen_mask_ready=str(Path(temporary)/'missing.json')),{}, {})

    def test_delivery_watcher_withholds_an_unmasked_ready_prediction(self):
        with tempfile.TemporaryDirectory(dir=p.HERE) as temporary:
            shot=dict(id='photo',mode='colorize',batch_id='batch',frames=1,scientific_screen_scene_id='photo',
                scientific_screen_mask_ready=str(Path(temporary)/'missing.json'))
            document=dict(source=dict(frame_count=1),shots=[shot]);updates=[]
            args=argparse.Namespace(manifest=Path('fixture'),batch='batch',wait=False,wait_for_queue=True,status_path=None)
            with mock.patch.object(p,'read_json',return_value=document),mock.patch.object(p,'validate_manifest',side_effect=lambda x:x), \
                mock.patch.object(p,'source_identity',return_value={}),mock.patch.object(p,'runtime_identity',return_value={}), \
                mock.patch.object(p,'ExclusiveLock'),mock.patch.object(p,'atomic_json',side_effect=lambda path,state:updates.append(dict(state))), \
                mock.patch.object(d,'choose_attempt',return_value=dict(attempt=1,output_sha256='verified')), \
                mock.patch.object(d,'merge_one',side_effect=AssertionError('Unmasked photo cannot enter delivery')), \
                mock.patch.object(d,'assemble_scope',side_effect=AssertionError('Missing matte blocks assembly')):
                d.watch(args)
            self.assertEqual(updates[-1]['merged_frames'],0)
            self.assertIn('photo',updates[-1]['scientific_masks_pending'])


if __name__=='__main__':main(verbosity=2)
