"""Measured two-sided endpoint chroma blend. Drafts retain original Y exactly.

Endpoint UV fields are held, not motion-warped; approximate alpha comes from
original-source Y measurements. Independent moving-neighborhood QA is required.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import json
import math
import copy
from pathlib import Path
import subprocess
import time
import numpy as np
import production as p
import delivery as d

METHOD = 'source-measured-alpha two-sided held-endpoint UV blend v1; exact original Y'
STATUS = p.HERE/'boundary_chroma_status.json'

def resolve_source_timing(plan):
    """Apply a hash-bound native timing correction before planning a treatment."""
    registry=p.HERE/'source_timing_overrides.json'
    entry=p.read_json(registry).get(str(plan['boundary_frame'])) if registry.exists() else None
    if not entry:return plan
    if p.sha256(entry['review'])!=entry['review_sha256']:raise ValueError('Native source timing review changed')
    review=p.read_json(entry['review'])
    if review.get('status')!='source_hardcut_timing_review_pass' or review.get('actual_hardcut_first_incoming_frame')!=entry['first_incoming_frame']:
        raise ValueError('Native hard-cut timing proof is invalid')
    result=copy.deepcopy(plan);start=plan['boundary_frame'];end=entry['first_incoming_frame']
    result.update(transition_kind='source_hardcut',support_start_frame=start,support_end_frame_exclusive=end,
        incoming_anchor_frames=[end,end+1,end+2],actual_hardcut_first_incoming_frame=end,
        native_source_alpha=[dict(frame_global=f,alpha_incoming_for_review=0.0) for f in range(start,end)],
        timing_refinement_review=entry['review'],timing_refinement_review_sha256=entry['review_sha256'],
        interpretation='Original outgoing source-photo UV until the exact hard cut; full incoming scene thereafter. No estimated dissolve ramp.')
    return result


def blend_uv(native, outgoing, incoming, alpha, pixels):
    if not math.isfinite(alpha) or not 0 <= alpha <= 1:
        raise ValueError('Invalid measured alpha')
    if len(native) != pixels*3 or outgoing.size != pixels*2 or incoming.size != pixels*2:
        raise ValueError('Native plane dimensions differ')
    uv = np.clip(np.rint(outgoing.astype(np.float32)*(1-alpha)+incoming.astype(np.float32)*alpha), 0, 255).astype(np.uint8)
    return native[:pixels] + uv.tobytes()


def validate_transition(plan, shot, per_frame=False):
    refined=resolve_source_timing(plan)
    if refined!=plan:
        raise ValueError('Superseded source dissolve timing: resolve hash-bound native hard-cut refinement before rendering')
    start, end = plan['support_start_frame'], plan['support_end_frame_exclusive']
    if not shot['start_frame'] <= start < end <= shot['end_frame'] or plan['boundary_frame'] != start:
        raise ValueError('Correction support must lie within the incoming shot')
    anchors = plan['incoming_anchor_frames']
    valid_anchor_count = len(anchors)>=1 if per_frame else len(anchors)==3
    if plan['outgoing_anchor_frame'] >= start or not valid_anchor_count or any(not end <= frame < shot['end_frame'] for frame in anchors):
        raise ValueError('Anchors must be outside measured blend support')
    alpha = {row['frame_global']:row['alpha_incoming_for_review'] for row in plan['native_source_alpha'] if start <= row['frame_global'] < end}
    if set(alpha) != set(range(start,end)) or any(not math.isfinite(a) or not 0 <= a <= 1 for a in alpha.values()):
        raise ValueError('Every support frame requires finite measured alpha')
    if any(alpha[i] > alpha[i+1] for i in range(start,end-1)):
        raise ValueError('For-review alpha must be monotone')
    return alpha


def anchor(path, local_frame, pixels, logfile):
    with logfile.open('w') as log:
        child=d.decoder(path,'yuv444p',log,local_frame,1)
        data=child.stdout.read(); child.stdout.close()
        if child.wait() or len(data)!=pixels*3:
            raise ValueError('Anchor native decode failed')
    return np.frombuffer(data[pixels:],np.uint8).copy()


def update(**values):
    p.atomic_json(STATUS,dict(updated_at=p.utc(),pid=__import__('os').getpid(),**values))


def repair(document, shot, outgoing_shot, base, outgoing_base, transition, measurement, measurement_path, overlap=None):
    alpha=validate_transition(transition,shot,per_frame=overlap is not None)
    override_path=p.HERE/'source_y_overrides.json'
    existing=p.read_json(override_path).get(shot['id'],{}) if override_path.exists() else {}
    if overlap is None and existing.get('status')=='changes_required':
        raise ValueError('Held-endpoint treatment was rejected by native QA; use verified per-frame overlap')
    pixels=document['source']['width']*document['source']['height']
    for item in [base,outgoing_base]:
        if item.get('status')!='draft_verified' or not item.get('exact_source_y') or not item.get('full_decode_verified'):
            raise ValueError('Both sides require verified original-Y native masters')
        if p.sha256(item['output']) != item['output_sha256']:
            raise ValueError('Endpoint master hash changed')
    method = METHOD if overlap is None else 'source-measured-alpha two-sided per-frame neural UV blend v2; exact original Y'
    if overlap:
        if not overlap.get('exact_source_y') or not overlap.get('full_decode_verified') or overlap['status']!='draft_verified':
            raise ValueError('Per-frame overlap requires a verified source-Y inference master')
        if not overlap['start_frame'] <= min(alpha) <= max(alpha) < overlap['end_frame']:
            raise ValueError('Per-frame overlap does not cover measured dissolve')
        if p.sha256(overlap['output'])!=overlap['output_sha256']:
            raise ValueError('Per-frame overlap payload changed')
        if overlap.get('field_origin')=='original_source_uv_fully_neutral_photo':
            if not overlap.get('exact_original_source_uv') or not overlap.get('whole_photo_mask_verified') or overlap.get('source_sha256')!=measurement['source_sha256']:
                raise ValueError('Original-photo UV requires native source and complete scene-mask proof')
            method='source-measured-alpha original-photo per-frame UV and masked incoming neural UV blend v3; exact original Y'
        elif overlap.get('field_origin')=='original_source_uv_canonical_passthrough':
            if outgoing_shot.get('mode')!='passthrough' or not overlap.get('exact_original_source_uv') or not overlap.get('canonical_passthrough_verified') or overlap.get('source_sha256')!=measurement['source_sha256']:
                raise ValueError('Original source UV requires a canonical passthrough scene and complete native proof')
            method='source-measured-alpha original-photo per-frame UV and masked incoming neural UV blend v3; exact original Y'
    key=p.json_digest(dict(method=method,base=base['output_sha256'],outgoing=outgoing_base['output_sha256'],
        overlap=overlap['output_sha256'] if overlap else None,transition=transition,source=measurement['source_sha256']))
    directory=d.BASE/'chroma_repairs'/shot['id']/f'treatment_{key[:16]}'
    directory.mkdir(parents=True,exist_ok=True)
    marker=directory/'treatment.json'
    if marker.exists():
        saved=p.read_json(marker)
        if saved.get('status')=='draft_verified' and saved.get('fingerprint')==key:
            p.reject_failed_chroma_review(saved['shot_id'],saved['output_sha256'])
            if Path(saved['output']).is_file() and p.sha256(saved['output'])==saved['output_sha256']:
                return saved,marker
    p.atomic_json(directory/'source_measurement.json',measurement)
    out_frame=transition['outgoing_anchor_frame']
    if not outgoing_shot['start_frame'] <= out_frame < outgoing_shot['end_frame']:
        raise ValueError('Outgoing anchor is not in adjacent shot')
    fields={}
    if overlap:
        with (directory/'overlap_decode.log').open('w') as log:
            reader=d.decoder(overlap['output'],'yuv444p',log,min(alpha)-overlap['start_frame'],len(alpha))
            try:
                for global_frame in sorted(alpha):
                    native=d.read_exact(reader.stdout,pixels*3)
                    if len(native)!=pixels*3: raise ValueError('Short native overlap decode')
                    fields[global_frame]=np.frombuffer(native[pixels:],np.uint8).copy()
                if reader.stdout.read(1): raise ValueError('Excess overlap support frames')
            finally:
                reader.stdout.close()
                code=reader.wait()
            if code: raise ValueError('Per-frame overlap decode failed')
        outgoing=incoming=None
    else:
        outgoing=anchor(outgoing_base['output'],out_frame-outgoing_shot['start_frame'],pixels,directory/'outgoing_anchor.log')
        incoming_frames=[anchor(base['output'],frame-shot['start_frame'],pixels,directory/f'incoming_anchor_{frame}.log') for frame in transition['incoming_anchor_frames']]
        incoming=np.median(np.stack(incoming_frames),axis=0).astype(np.uint8)

    def patch(native, global_frame):
        if global_frame not in alpha: return native
        incoming_uv=np.frombuffer(native[pixels:],np.uint8) if overlap else incoming
        return blend_uv(native,fields[global_frame] if overlap else outgoing,incoming_uv,alpha[global_frame],pixels)
    output=directory/'source_y_master.mkv'
    record=dict(schema_version=1,status='repairing',quality_acceptance='pending',shot_id=shot['id'],
        start_frame=shot['start_frame'],end_frame=shot['end_frame'],frames=shot['frames'],method=method,
        fingerprint=key,base_output=base['output'],base_output_sha256=base['output_sha256'],
        outgoing_shot_id=outgoing_shot['id'],outgoing_output=outgoing_base['output'],outgoing_output_sha256=outgoing_base['output_sha256'],
        source_sha256=measurement['source_sha256'],measurement_path=str(measurement_path),measurement_sha256=p.sha256(measurement_path),
        transition=transition,output=str(output),started_at=p.utc(),
        outgoing_uv_sha256=hashlib.sha256(outgoing.tobytes()).hexdigest() if outgoing is not None else None,
        incoming_median_uv_sha256=hashlib.sha256(incoming.tobytes()).hexdigest() if incoming is not None else None,
        overlap_master=overlap,
        limitations=['Source alpha is a robust estimate affected by subject/camera motion and film noise.',
            'Endpoint UV fields are held without motion compensation.' if not overlap else (
                'Outgoing scientific photograph uses exact original source UV on every support frame; incoming scene uses source-masked same-frame neural UV.'
                if overlap.get('field_origin') in {'original_source_uv_fully_neutral_photo','original_source_uv_canonical_passthrough'} else
                'Both UV fields are predicted from the actual source frame using different scene references; colors remain interpretive.'),
            'Every support frame and moving neighborhood requires independent visual review.',
            'Luminance and geometry remain original. No automatic visual acceptance.'])
    p.atomic_json(marker,record)
    source=document['source']; rate=f'{source["fps_num"]}/{source["fps_den"]}'
    command=[str(p.FFMPEG),'-v','error','-xerror','-y','-f','rawvideo','-pix_fmt','yuv444p','-s',f'{source["width"]}x{source["height"]}',
        '-framerate',rate,'-i','pipe:0','-an','-sn','-c:v','ffv1','-level','3','-threads','2','-pix_fmt','yuv444p','-color_range','tv','-colorspace','bt470bg',str(output)]
    try:
        with (directory/'base_decode.log').open('w') as blog,(directory/'encode.log').open('w') as elog:
            reader=d.decoder(base['output'],'yuv444p',blog)
            encoder=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=elog,stderr=elog)
            try:
                for index in range(shot['frames']):
                    native=d.read_exact(reader.stdout,pixels*3)
                    if len(native)!=pixels*3: raise ValueError('Short base decode')
                    global_frame=shot['start_frame']+index
                    encoder.stdin.write(patch(native,global_frame))
                    if index%96==0: update(stage='encoding',shot_id=shot['id'],done=index+1,total=shot['frames'])
                if reader.stdout.read(1): raise ValueError('Excess base frames')
            finally:
                reader.stdout.close()
                with contextlib.suppress(BrokenPipeError,OSError): encoder.stdin.close()
                codes=[reader.wait(),encoder.wait()]
            if any(codes): raise RuntimeError(f'Boundary repair failed: {codes}')
        update(stage='verifying_all_planes',shot_id=shot['id'])
        y_digest=hashlib.sha256(); outside_digest=hashlib.sha256(); full_digest=hashlib.sha256()
        with (directory/'verify_base.log').open('w') as blog,(directory/'verify_output.log').open('w') as olog:
            readers=[d.decoder(base['output'],'yuv444p',blog),d.decoder(output,'yuv444p',olog)]
            try:
                for index in range(shot['frames']):
                    before,after=[d.read_exact(child.stdout,pixels*3) for child in readers]
                    if len(before)!=pixels*3 or len(after)!=pixels*3 or before[:pixels]!=after[:pixels]:
                        raise ValueError('Treatment changed original Y or frame count')
                    global_frame=shot['start_frame']+index
                    expected=patch(before,global_frame)
                    if expected!=after: raise ValueError('UV differs from measured treatment or outside support')
                    y_digest.update(after[:pixels]); full_digest.update(after)
                    if global_frame not in alpha: outside_digest.update(after[pixels:])
                if any(child.stdout.read(1) for child in readers): raise ValueError('Excess verified output frames')
            finally:
                for child in readers: child.stdout.close()
                codes=[child.wait() for child in readers]
            if any(codes): raise ValueError('Full verification decode failed')
        if y_digest.hexdigest()!=base['source_y']['sha256']:
            raise ValueError('Treatment Y does not match verified original source digest')
        d.verify_video_geometry(output,source)
        timing=d.verify_timestamps(output,shot['frames'],source)
        record.update(status='draft_verified',exact_source_y=True,exact_outside_support_uv=True,full_decode_verified=True,
            exact_measured_uv=True,verified_decoded_frames=shot['frames'],changed_support_frames=len(alpha),
            y_sha256=y_digest.hexdigest(),outside_support_uv_sha256=outside_digest.hexdigest(),full_yuv_sha256=full_digest.hexdigest(),
            timing=timing,output_sha256=p.sha256(output),finished_at=p.utc())
    except BaseException as error:
        record.update(status='failed',error=str(error),finished_at=p.utc()); raise
    finally:
        p.atomic_json(marker,record)
    p.reject_failed_chroma_review(record['shot_id'],record['output_sha256'])
    return record,marker


def main(args):
    document=p.validate_manifest(p.read_json(args.manifest))
    measurement=p.read_json(args.measurement)
    identity=p.source_identity(document['source'])
    if measurement['source_sha256']!=identity['sha256']: raise ValueError('Source measurement identity differs')
    registry=p.read_json(args.registry)['merge_registry']
    bases={}
    for shot_id,item in registry.items():
        path=Path(item.get('base_output') or item['output'])
        bases[shot_id]=p.read_json(path.parent/'merge.json')
    requested={int(value) for value in args.boundaries.split(',')}
    transitions=[row for row in measurement['transitions'] if row['boundary_frame'] in requested]
    if len(transitions)!=len(requested): raise ValueError('Missing measured transition')
    override_path=p.HERE/'source_y_overrides.json'
    with p.ExclusiveLock(p.HERE/'boundary_chroma.lock'):
        for transition in transitions:
            boundary=transition['boundary_frame']
            shot=next(row for row in document['shots'] if row['start_frame']==boundary)
            outgoing=next(row for row in document['shots'] if row['end_frame']==boundary)
            record,marker=repair(document,shot,outgoing,bases[shot['id']],bases[outgoing['id']],transition,measurement,args.measurement)
            overrides=p.read_json(override_path) if override_path.exists() else {}
            overrides[shot['id']]=dict(receipt=str(marker),output_sha256=record['output_sha256'],status='active_pending_quality_review',
                base_output_sha256=record['base_output_sha256'],support_start_frame=transition['support_start_frame'],support_end_frame_exclusive=transition['support_end_frame_exclusive'])
            p.atomic_json(override_path,overrides)
            print(json.dumps(dict(stage='chroma_repair_ready',shot_id=shot['id'],receipt=str(marker),output=record['output'])),flush=True)
        update(stage='draft_repairs_ready',boundaries=sorted(requested),acceptance=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=p.PROJECT/'scenes/first_batch_manifest.json')
    parser.add_argument('--measurement',type=Path,default=p.PROJECT/'scenes/qc/dissolves/source_dissolve_map.json')
    parser.add_argument('--registry',type=Path,default=p.HERE/'delivery_status.json')
    parser.add_argument('--boundaries',default='4048')
    main(parser.parse_args())
