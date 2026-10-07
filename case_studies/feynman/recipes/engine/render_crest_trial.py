"""Render a versioned whole-shot crest trial, with exact Y/pixel-scope proof."""
import contextlib
import hashlib
from pathlib import Path
import shutil
import subprocess
import numpy as np
import production as p
import delivery as d
from crest_opacity_model import SourceCrestOpacity

STATUS=p.HERE/'crest_full_trial_status.json'
SUPPORT=(79298,79525)


def status(stage,**details):p.atomic_json(STATUS,dict(stage=stage,updated_at=p.utc(),delivery_acceptance=False,**details))


def encode(path,source,fmt,log):
    command=[str(p.FFMPEG),'-v','error','-xerror','-y','-f','rawvideo','-pix_fmt',fmt,
        '-s',f'{source["width"]}x{source["height"]}','-framerate',f'{source["fps_num"]}/{source["fps_den"]}',
        '-i','pipe:0','-an','-sn','-c:v','ffv1','-level','3','-threads','2','-pix_fmt',fmt]
    if fmt!='gray':command+=['-color_range','tv','-colorspace','bt470bg']
    return subprocess.Popen(command+[str(path)],stdin=subprocess.PIPE,stdout=log,stderr=log)


def main():
    review=p.PROJECT/'scenes/qc/overlays/crest/v04_still_method_review.json'
    expected='62096f0ae03da22c9040dfe40c1665f60b937532c8046105dcbcccc422a368b8'
    if p.sha256(review)!=expected:raise ValueError('Reviewed still-method evidence changed')
    manifest=p.read_json(p.HERE/'batch_06_manifest.json');source=manifest['source']
    attempt=p.read_json(p.RENDER/'shot_078641/attempt_001/attempt.json')
    base_path=d.BASE/'shots/shot_078641/attempt_001_abc73bbe4666/merge.json';base=p.read_json(base_path)
    if p.sha256(base['output'])!=base['output_sha256']:raise ValueError('Current whole-shot baseline changed')
    cache=p.HERE/'crest_opacity_trial_v03/native_samples.npz';still=p.HERE/'crest_opacity_trial_v04/trial.json'
    still_record=p.read_json(still)
    if still_record['native_still_cache_sha256']!=p.sha256(cache):raise ValueError('Reviewed native still cache changed')
    model_sha=p.sha256(p.HERE/'crest_opacity_model.py');implementation_sha=p.sha256(__file__)
    fingerprint=p.json_digest(dict(source=source['sha256'],baseline=base['output_sha256'],review=expected,
        model=model_sha,implementation=implementation_sha,cache=p.sha256(cache),support=SUPPORT))
    root=d.BASE/'overlay_trials/shot_078641'/('crest_'+fingerprint[:16]);root.mkdir(parents=True,exist_ok=True)
    receipt=root/'treatment.json';output=root/'source_y_master.mkv';alpha_path=root/'source_opacity_ffv1.mkv'
    if receipt.exists():
        row=p.read_json(receipt)
        if row.get('status')=='draft_verified' and p.sha256(output)==row['output_sha256'] and p.sha256(alpha_path)==row['alpha_sha256']:
            status('draft_trial_ready_pending_native_review',receipt=str(receipt),output_sha256=row['output_sha256']);return
    needed=10+1.3*(Path(base['output']).stat().st_size+80*2**20)/2**30
    if shutil.disk_usage(p.WORKSPACE).free/2**30<needed:raise ValueError('Bounded CPU trial does not fit unchanged disk reserve')
    with np.load(cache) as samples:model=SourceCrestOpacity(samples)
    height,width=source['height'],source['width'];pixels=height*width
    rows=[];input_y=hashlib.sha256();source_support=hashlib.sha256();outside=hashlib.sha256();expected_yuv=hashlib.sha256()
    with (root/'decode.log').open('w') as log,(root/'encode.log').open('w') as enc_log,(root/'alpha_encode.log').open('w') as alpha_log:
        before=d.decoder(base['output'],'yuv444p',log)
        original=d.decoder(attempt['source_clip']['path'],'yuv444p',log,SUPPORT[0]-attempt['source_clip']['source_clip_start_frame'],SUPPORT[1]-SUPPORT[0])
        writer=encode(output,source,'yuv444p',enc_log);alpha_writer=encode(alpha_path,source,'gray',alpha_log)
        try:
            for index in range(base['frames']):
                frame=base['start_frame']+index;raw=d.read_exact(before.stdout,pixels*3)
                if len(raw)!=pixels*3:raise ValueError('Short canonical baseline')
                current=np.frombuffer(raw,np.uint8).reshape(3,height,width);after=current.copy()
                if SUPPORT[0]<=frame<SUPPORT[1]:
                    original_raw=d.read_exact(original.stdout,pixels*3)
                    if len(original_raw)!=pixels*3:raise ValueError('Short exact original-source support')
                    native=np.frombuffer(original_raw,np.uint8).reshape(3,height,width)
                    _,alpha,proof=model.apply(frame,native,current)
                    alpha8=np.rint(alpha*255).astype(np.uint8);weight=alpha8.astype(np.float32)/255
                    after[1:]=np.rint(current[1:].astype(np.float32)*(1-weight)+native[1:].astype(np.float32)*weight).clip(0,255).astype(np.uint8)
                    if not np.array_equal(after[0],native[0]):raise ValueError('Crest trial changed original source Y')
                    if not np.array_equal(after[1:,alpha8==0],current[1:,alpha8==0]):raise ValueError('Crest trial changed UV outside source-opacity mask')
                    source_support.update(original_raw);outside.update(after[1:,alpha8==0].tobytes())
                    alpha_writer.stdin.write(alpha8.tobytes());rows.append(dict(frame_global=frame,source_global_strength=proof['strength'],
                        alpha_nonzero_pixels=int(np.count_nonzero(alpha8)),alpha_sha256=hashlib.sha256(alpha8.tobytes()).hexdigest(),geometry=proof['geometry']))
                else:outside.update(after[1:].tobytes())
                encoded=after.tobytes();input_y.update(raw[:pixels]);expected_yuv.update(encoded);writer.stdin.write(encoded)
                if index%32==0:status('rendering_cpu_source_opacity_trial',done=index+1,total=base['frames'],frame_global=frame)
            if before.stdout.read(1) or original.stdout.read(1):raise ValueError('Excess mapped frames')
        finally:
            for child in [before,original]:child.stdout.close()
            for child in [writer,alpha_writer]:
                with contextlib.suppress(OSError):child.stdin.close()
            codes=[child.wait() for child in [before,original,writer,alpha_writer]]
        if any(codes):raise ValueError('Crest trial media process failed')
    if input_y.hexdigest()!=base['source_y']['sha256']:raise ValueError('Native input differs from independently bound source-Y proof')
    status('verifying_full_native_trial',output=str(output))
    actual_y=hashlib.sha256();actual_yuv=hashlib.sha256();actual_outside=hashlib.sha256();alpha_hash=hashlib.sha256()
    with (root/'verify.log').open('w') as log:
        children=[d.decoder(path,fmt,log) for path,fmt in [(base['output'],'yuv444p'),(output,'yuv444p'),(alpha_path,'gray')]]
        try:
            for index in range(base['frames']):
                frame=base['start_frame']+index;old,new=[d.read_exact(c.stdout,pixels*3) for c in children[:2]]
                if len(old)!=pixels*3 or len(new)!=pixels*3 or old[:pixels]!=new[:pixels]:raise ValueError('Final decode changed frame coverage or Y')
                actual_y.update(new[:pixels]);actual_yuv.update(new)
                if SUPPORT[0]<=frame<SUPPORT[1]:
                    mask=d.read_exact(children[2].stdout,pixels)
                    if len(mask)!=pixels:raise ValueError('Short verified alpha mapping')
                    record=rows[frame-SUPPORT[0]]
                    if hashlib.sha256(mask).hexdigest()!=record['alpha_sha256']:raise ValueError('Encoded opacity changed')
                    zero=np.frombuffer(mask,np.uint8)==0
                    old_uv=np.frombuffer(old[pixels:],np.uint8).reshape(2,pixels);new_uv=np.frombuffer(new[pixels:],np.uint8).reshape(2,pixels)
                    if not np.array_equal(old_uv[:,zero],new_uv[:,zero]):raise ValueError('Final decode changed outside-mask UV')
                    actual_outside.update(new_uv[:,zero].tobytes());alpha_hash.update(mask)
                else:
                    if old!=new:raise ValueError('Final decode changed outside temporal support')
                    actual_outside.update(new[pixels:])
            if any(c.stdout.read(1) for c in children):raise ValueError('Excess verified media')
        finally:
            for child in children:child.stdout.close()
            codes=[child.wait() for child in children]
        if any(codes):raise ValueError('Full trial verification decode failed')
    if actual_yuv.hexdigest()!=expected_yuv.hexdigest() or actual_y.hexdigest()!=input_y.hexdigest() or actual_outside.hexdigest()!=outside.hexdigest():
        raise ValueError('Encoded trial planes differ from bounded source-driven computation')
    timing=d.verify_timestamps(output,base['frames'],source);d.verify_video_geometry(output,source)
    if p.sha256(base['output'])!=base['output_sha256']:raise ValueError('Baseline changed during trial')
    p.atomic_json(root/'per_frame_source_opacity.json',rows)
    record=dict(schema_version=1,status='draft_verified',quality_acceptance='dense_native_overlay_review_pending',
        method='original-source stroke opacity attenuates prediction UV toward same-frame source UV; original Y exact',fingerprint=fingerprint,
        shot_id=base['shot_id'],start_frame=base['start_frame'],end_frame=base['end_frame'],frames=base['frames'],
        base_output=base['output'],base_output_sha256=base['output_sha256'],source_sha256=source['sha256'],source_y=base['source_y'],
        output=str(output),output_sha256=p.sha256(output),alpha_path=str(alpha_path),alpha_sha256=p.sha256(alpha_path),
        alpha_start_frame=SUPPORT[0],alpha_end_frame_exclusive=SUPPORT[1],alpha_decoded_sha256=alpha_hash.hexdigest(),
        support_start_frame=SUPPORT[0],support_end_frame_exclusive=SUPPORT[1],full_decode_verified=True,exact_source_y=True,
        exact_outside_support_uv=True,exact_outside_spatial_alpha_uv=True,full_yuv_sha256=actual_yuv.hexdigest(),
        source_support_yuv_sha256=source_support.hexdigest(),outside_support_uv_sha256=actual_outside.hexdigest(),
        still_method_review=str(review),still_method_review_sha256=expected,model_sha256=model_sha,implementation_sha256=implementation_sha,
        per_frame_source_geometry=str(root/'per_frame_source_opacity.json'),timing=timing,delivery_registry_changed=False,delivery_acceptance=False,
        limitations=['Source opacity is an approximation from aligned before/after source plates and local ink brightness.',
            'All227 support frames, native thin strokes, and both fades require independent motion/color review.',
            'This is a whole-shot candidate only; future disjoint entry treatments must preserve this reviewed tail if selected.'])
    p.atomic_json(receipt,record);status('draft_trial_ready_pending_native_review',receipt=str(receipt),output_sha256=record['output_sha256'])


if __name__=='__main__':
    try:main()
    except BaseException as error:status('failed',error=str(error));raise
