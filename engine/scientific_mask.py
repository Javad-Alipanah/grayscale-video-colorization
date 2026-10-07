"""Apply source-neutral photo UV to one scene hypothesis before dissolves.

Semantic geometry/foreground correctness remains an independent visual QA gate.
This module proves exact source Y, source UV at matte255 and model UV at matte0.
"""
import contextlib
import hashlib
from fractions import Fraction
from pathlib import Path
import shutil
import subprocess
import time
import numpy as np
import production as p

METHOD='native source UV through binary scientific-screen matte with foreground exclusion v1'

class ScientificMaskPending(ValueError):
    pass

def load(shot,source,identity,allow_trial=False):
    scene_id=shot.get('scientific_screen_scene_id')
    if not scene_id or shot.get('mode')!='colorize':return None
    marker=p.resolve(shot['scientific_screen_mask_ready'])
    if not marker.exists():raise ScientificMaskPending(f'Native scientific-screen matte is not published for {scene_id}')
    record=p.read_json(marker)
    if record.get('status')=='source_mask_trial_ready' and not allow_trial:
        raise ScientificMaskPending(f'Scientific-screen matte still requires native review for {scene_id}')
    if record.get('status') not in {'source_mask_trial_ready','source_mask_native_review_pass'}:
        raise ScientificMaskPending(f'Scientific-screen matte is held for {scene_id}: {record.get("status")}')
    if record['status']=='source_mask_native_review_pass':
        review_path=p.resolve(record.get('review_receipt',''))
        if not record.get('native_visual_review_pass') or not review_path.is_file() or p.sha256(review_path)!=record.get('review_receipt_sha256'):
            raise ScientificMaskPending('Scientific-screen native review receipt is missing or changed')
        review=p.read_json(review_path)
        if review.get('status')!='local_source_mask_pass' or review.get('scene_id')!=scene_id or review.get('mask_sha256')!=record.get('mask_sha256'):
            raise ScientificMaskPending('Scientific-screen native review is not bound to this matte')
    if record.get('schema_version')!=1 or record.get('scene_id')!=scene_id or record.get('source_sha256')!=identity['sha256']:
        raise ValueError('Scientific matte scene/source binding is invalid')
    if any(record.get(key)!=source[key] for key in ['width','height','fps_num','fps_den']):raise ValueError('Scientific matte native geometry/cadence differs')
    if not record.get('foreground_exclusions_included') or record.get('pixel_format')!='gray':raise ValueError('A native gray matte with foreground exclusions is required')
    if not record['start_frame']<=shot['start_frame']<shot['end_frame']<=record['end_frame']:
        raise ScientificMaskPending('Scientific matte does not cover this scene hypothesis and its dissolve handles')
    path=p.resolve(record['mask_path'])
    if not path.is_file() or p.sha256(path)!=record['mask_sha256']:raise ScientificMaskPending('Scientific matte payload is incomplete or changed')
    config={key:record[key] for key in ['scene_id','source_sha256','width','height','fps_num','fps_den','start_frame','end_frame','mask_sha256','foreground_exclusions_included']}
    return dict(record=record,path=path,marker=marker,content_digest=p.json_digest(config))

def equivalent_prior_output(document,shot,base,identity,config,directory,callback):
    """Keep reviewed canonical bytes when only external matte handles changed.

    A current strict geometry/coverage review is already required by load().
    This proof compares every requested decoded gray mask byte, not a marker
    timestamp or a sampled region. It never reuses a different prediction base.
    """
    import delivery as d
    proof_path=directory/'canonical_mask_equivalence.json'
    expected_bytes=shot['frames']*document['source']['width']*document['source']['height']
    candidates=sorted(directory.parent.glob('mask_*/mask.json'),key=lambda path:path.stat().st_mtime,reverse=True)
    for marker in candidates:
        previous=p.read_json(marker)
        if not (previous.get('status')=='draft_verified' and previous.get('exact_source_y') and previous.get('full_decode_verified')
                and previous.get('exact_source_uv_inside_mask') and previous.get('exact_prediction_uv_outside_mask')
                and previous.get('source_sha256')==identity['sha256']
                and previous.get('source_y_base_output_sha256')==base['output_sha256']
                and (previous.get('start_frame'),previous.get('end_frame'),previous.get('frames'))==(shot['start_frame'],shot['end_frame'],shot['frames'])):
            continue
        frozen=marker.parent/'mask.snapshot.mkv';old_ready_path=marker.parent/'mask_ready.snapshot.json'
        if not frozen.is_file() or not old_ready_path.is_file() or not Path(previous['output']).is_file():continue
        old_ready=p.read_json(old_ready_path)
        if not old_ready['start_frame']<=shot['start_frame']<shot['end_frame']<=old_ready['end_frame']:continue
        if p.sha256(frozen)!=previous['scientific_mask_sha256'] or p.sha256(previous['output'])!=previous['output_sha256']:continue
        key=p.json_digest(dict(source=identity['sha256'],base=base['output_sha256'],old_mask=p.sha256(frozen),
            current_mask=config['record']['mask_sha256'],old_output=previous['output_sha256'],start=shot['start_frame'],end=shot['end_frame']))
        if proof_path.exists():
            proof=p.read_json(proof_path)
            if (proof.get('fingerprint')==key and proof.get('exact_requested_mask_bytes') and proof.get('decoded_mask_bytes')==expected_bytes
                    and proof.get('prior_receipt_sha256')==p.sha256(marker)):
                return dict(previous,canonical_mask_equivalence_receipt=str(proof_path))
        digests=[]
        for label,path,start in [('previous',frozen,old_ready['start_frame']),('current',config['path'],config['record']['start_frame'])]:
            local=shot['start_frame']-start
            command=[str(p.FFMPEG),'-v','error','-xerror','-threads','2','-filter_threads','2','-i',str(path),'-map','0:v:0',
                '-vf',f'trim=start_frame={local}:end_frame={local+shot["frames"]},setpts=PTS-STARTPTS',
                '-frames:v',str(shot['frames']),'-an','-sn','-pix_fmt','gray','-f','rawvideo','pipe:1']
            digests.append(d.hash_command(command,directory/f'equivalence_{label}.log',callback))
        if digests[0]!=digests[1] or digests[0]['decoded_bytes']!=expected_bytes:continue
        proof=dict(schema_version=1,status='exact_requested_mask_coverage_equivalence',fingerprint=key,verified_at=p.utc(),
            scene_id=shot.get('scientific_screen_scene_id'),start_frame=shot['start_frame'],end_frame=shot['end_frame'],frames=shot['frames'],
            source_sha256=identity['sha256'],base_output_sha256=base['output_sha256'],prior_receipt=str(marker),prior_receipt_sha256=p.sha256(marker),
            retained_output=previous['output'],retained_output_sha256=previous['output_sha256'],prior_mask_sha256=p.sha256(frozen),
            current_mask_sha256=config['record']['mask_sha256'],current_native_ready_snapshot=config['record'],
            exact_requested_mask_bytes=True,decoded_mask_bytes=expected_bytes,decoded_mask_sha256=digests[0]['sha256'],
            semantics='Current strict source-native mask coverage is byte-identical over this entire shot. Retain its verified original-Y/source-UV protected video and existing scoped QA; no new visual acceptance.')
        p.atomic_json(proof_path,proof)
        return dict(previous,canonical_mask_equivalence_receipt=str(proof_path))
    return None


def apply(document,shot,attempt,base,identity,config,callback):
    import delivery as d
    if config is None:return base
    key=p.json_digest(dict(base=base['output_sha256'],mask=config['content_digest'],method=METHOD,start=shot['start_frame'],end=shot['end_frame']))
    directory=d.BASE/'scientific_masks'/shot['id']/('mask_'+key[:16]);directory.mkdir(parents=True,exist_ok=True)
    receipt=directory/'mask.json';output=directory/'source_y_master.mkv'
    if receipt.exists():
        previous=p.read_json(receipt)
        if previous.get('status')=='draft_verified' and previous.get('fingerprint')==key and Path(previous['output']).is_file() and p.sha256(previous['output'])==previous['output_sha256']:return previous
    equivalent=equivalent_prior_output(document,shot,base,identity,config,directory,callback)
    if equivalent:return equivalent
    if p.sha256(base['output'])!=base['output_sha256']:raise ValueError('Source-Y hypothesis changed before screen masking')
    frozen=directory/'mask.snapshot.mkv';shutil.copy2(config['path'],frozen)
    if p.sha256(frozen)!=config['record']['mask_sha256']:raise ScientificMaskPending('Matte changed while freezing its snapshot')
    p.atomic_json(directory/'mask_ready.snapshot.json',config['record'])
    source=document['source'];w,h=source['width'],source['height'];pixels=w*h;frames=shot['frames']
    info=p.probe(frozen,count=True)
    if (int(info.get('nb_read_frames',-1)),info['width'],info['height'],info['pix_fmt'])!=(config['record']['end_frame']-config['record']['start_frame'],w,h,'gray'):
        raise ValueError('Matte video frame count or native geometry differs from its receipt')
    if info['codec_name']!='ffv1' or Fraction(info['r_frame_rate'])!=Fraction(source['fps_num'],source['fps_den']):
        raise ValueError('Matte must be lossless FFV1 at native source cadence')
    clip=attempt['source_clip']
    if clip['source_sha256']!=identity['sha256'] or not clip['source_clip_start_frame']<=shot['start_frame']<shot['end_frame']<=clip['source_clip_end_frame']:
        raise ValueError('Scientific source-chroma cache mapping does not cover the hypothesis')
    if p.sha256(clip['path'])!=clip.get('sha256'):raise ValueError('Native source-chroma cache checksum changed')
    result=dict(base,status='masking',quality_acceptance='pending',fingerprint=key,output=str(output),
        source_y_base_output=base['output'],source_y_base_output_sha256=base['output_sha256'],scientific_screen_scene_id=shot['scientific_screen_scene_id'],
        scientific_mask_receipt=str(receipt),scientific_mask_ready=str(config['marker']),scientific_mask_sha256=config['record']['mask_sha256'],
        method=METHOD,application_order='Per-scene neural hypothesis before measured source-alpha dissolve compositing.',
        semantic_mask_quality_acceptance='pending independent native boundary, foreground and temporal review',started_at=p.utc())
    p.atomic_json(receipt,result);began=time.perf_counter()
    expected=hashlib.sha256();source_y=hashlib.sha256();whole_frames=[];source_pixels=0
    command=[str(p.FFMPEG),'-v','error','-xerror','-y','-f','rawvideo','-pix_fmt','yuv444p','-s',f'{w}x{h}',
        '-framerate',f'{source["fps_num"]}/{source["fps_den"]}','-i','pipe:0','-an','-sn','-c:v','ffv1','-level','3','-threads','2',
        '-pix_fmt','yuv444p','-color_range','tv','-colorspace','bt470bg',str(output)]
    try:
        with (directory/'source.log').open('w') as sl,(directory/'base.log').open('w') as bl,(directory/'mask.log').open('w') as ml,(directory/'encode.log').open('w') as el:
            original=d.decoder(clip['path'],'yuv444p',sl,shot['start_frame']-clip['source_clip_start_frame'],frames)
            prediction=d.decoder(base['output'],'yuv444p',bl)
            matte=d.decoder(frozen,'gray',ml,shot['start_frame']-config['record']['start_frame'],frames)
            encoder=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=el,stderr=el)
            try:
                for index in range(frames):
                    native=d.read_exact(original.stdout,pixels*3);before=d.read_exact(prediction.stdout,pixels*3);mask=d.read_exact(matte.stdout,pixels)
                    if (len(native),len(before),len(mask))!=(pixels*3,pixels*3,pixels):raise ValueError('Short hypothesis/source/matte decode')
                    if native[:pixels]!=before[:pixels]:raise ValueError('Base Y does not equal original source Y')
                    values=np.frombuffer(mask,np.uint8)
                    if not np.all((values==0)|(values==255)):raise ValueError('Matte must be binary; no unreviewed fractional edge weights')
                    selected=values==255;source_pixels+=int(selected.sum())
                    if selected.all():whole_frames.append(shot['start_frame']+index)
                    planes=np.frombuffer(before,np.uint8).reshape(3,pixels).copy();native_planes=np.frombuffer(native,np.uint8).reshape(3,pixels)
                    planes[1:,selected]=native_planes[1:,selected]
                    payload=planes.tobytes();encoder.stdin.write(payload);expected.update(payload);source_y.update(native[:pixels])
                    if index%48==0 or index+1==frames:callback(phase='masking_scientific_photo',done=index+1,total=frames)
                if any(child.stdout.read(1) for child in [original,prediction,matte]):raise ValueError('Excess frames in source/hypothesis/matte')
            finally:
                for child in [original,prediction,matte]:child.stdout.close()
                with contextlib.suppress(BrokenPipeError,OSError):encoder.stdin.close()
                codes=[child.wait() for child in [original,prediction,matte,encoder]]
            if any(codes):raise RuntimeError(f'Photo matte decoding/encoding failed: {codes}')
        callback(phase='verifying_scientific_photo_planes')
        d.verify_video_geometry(output,source)
        actual=d.hash_command([str(p.FFMPEG),'-v','error','-xerror','-i',str(output),'-map','0:v:0','-an','-sn','-f','rawvideo','-pix_fmt','yuv444p','pipe:1'],directory/'verify_planes.log',callback)
        if actual!={'sha256':expected.hexdigest(),'decoded_bytes':frames*pixels*3}:raise ValueError('Lossless mask output differs from complete expected native planes')
        timing=d.verify_timestamps(output,frames,source)
        result.update(status='draft_verified',exact_source_y=True,exact_source_uv_inside_mask=True,exact_prediction_uv_outside_mask=True,
            full_decode_verified=True,verified_decoded_frames=frames,source_y=dict(sha256=source_y.hexdigest(),decoded_bytes=frames*pixels),
            decoded_yuv_sha256=expected.hexdigest(),source_uv_pixel_count=source_pixels,full_source_uv_passthrough_frames_global=whole_frames,
            output_sha256=p.sha256(output),timing=timing,finished_at=p.utc(),wall_seconds=time.perf_counter()-began)
    except BaseException as error:
        result.update(status='failed',error=str(error),finished_at=p.utc());raise
    finally:p.atomic_json(receipt,result)
    return result
