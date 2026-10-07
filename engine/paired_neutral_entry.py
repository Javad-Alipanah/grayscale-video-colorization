"""One measured photo-entry patch across unchanged canonical shot partitions.

This creates a joint native review artifact; it never changes the delivery
selection. The incoming field is each actual original frame's source UV.
"""
import contextlib
import hashlib
import math
from pathlib import Path
import subprocess
import numpy as np
import production as p
import delivery as d
from boundary_chroma import blend_uv

METHOD='source-measured continuous neutral-photo entry across canonical partitions v1; original Y exact'


def measured_alpha(review, shots, neural_incoming=False):
    if 'recommended_trial_support_start_frame' in review:
        start=review['recommended_trial_support_start_frame'];end=review['recommended_trial_support_end_frame_exclusive']
        rows=review['alpha_for_trial']
    else:
        start=review['support_start_frame'];end=review['support_end_frame_exclusive']
        values=review['incoming_alpha_for_trial']
        if len(values)!=end-start:raise ValueError('Compact source review omits a support-frame coefficient')
        rows=[dict(frame_global=start+i,incoming_alpha=a) for i,a in enumerate(values)]
    if len(shots)!=2 or shots[0]['end_frame']!=shots[1]['start_frame']:
        raise ValueError('Joint treatment requires two unchanged adjacent partitions')
    split=shots[1]['start_frame']
    if not shots[0]['start_frame']<=start<split<end<=shots[1]['end_frame']:
        raise ValueError('Joint support must span exactly these two partitions')
    if not neural_incoming and shots[1]['mode']!='passthrough':raise ValueError('Incoming photograph must be canonical source passthrough')
    if neural_incoming and shots[1]['mode']!='colorize':raise ValueError('Neural incoming hypothesis requires a colorized scene')
    if [r['frame_global'] for r in rows]!=list(range(start,end)):
        raise ValueError('Joint support requires one source-derived alpha for each exact frame')
    alpha={r['frame_global']:r['incoming_alpha'] for r in rows}
    if any(not math.isfinite(a) or not 0<=a<=1 for a in alpha.values()) or any(alpha[f]>alpha[f+1] for f in range(start,end-1)):
        raise ValueError('Joint alpha must be finite, bounded and monotone')
    return alpha


def support_fields(path,start,count,pixels,log_path):
    fields=[]
    with log_path.open('w') as log:
        reader=d.decoder(path,'yuv444p',log,start,count)
        try:
            for _ in range(count):
                frame=d.read_exact(reader.stdout,pixels*3)
                if len(frame)!=pixels*3:raise ValueError('Short hypothesis support decode')
                fields.append(frame)
            if reader.stdout.read(1):raise ValueError('Excess hypothesis support frames')
        finally:
            reader.stdout.close();code=reader.wait()
        if code:raise ValueError('Hypothesis support decode failed')
    return fields


def parent_support_frames(old):
    if old.get('verified_support_union_global') is not None:return set(old['verified_support_union_global'])
    support=old.get('transition',old)
    return set(range(support['support_start_frame'],support['support_end_frame_exclusive']))


def build(document,shots,bases,selected,parents,overlap,identity,review_path,callback,incoming_overlap=None):
    review=p.read_json(review_path);alpha=measured_alpha(review,shots,neural_incoming=incoming_overlap is not None)
    method=METHOD if incoming_overlap is None else 'source-measured dual same-frame neural UV across canonical partitions v2; original Y and disjoint prior treatment exact'
    if review['source_sha256']!=identity['sha256']:raise ValueError('Joint source review identity differs')
    start,end=min(alpha),max(alpha)+1;pixels=document['source']['width']*document['source']['height']
    if not overlap['start_frame']<=start<end<=overlap['end_frame'] or (incoming_overlap is None and not overlap.get('scientific_mask_receipt')):
        raise ValueError('Outgoing scene must have a reviewed screen mask throughout the joint support')
    if incoming_overlap is not None and not incoming_overlap['start_frame']<=start<end<=incoming_overlap['end_frame']:
        raise ValueError('Incoming same-frame field must cover the entire joint support')
    for item in [*bases,*selected,overlap,*([incoming_overlap] if incoming_overlap else [])]:
        if item.get('status')!='draft_verified' or not item.get('exact_source_y') or not item.get('full_decode_verified'):
            raise ValueError('Every input must be a verified original-Y native hypothesis')
        if p.sha256(item['output'])!=item['output_sha256']:raise ValueError('Joint input changed')
    key_fields=dict(method=method,source=identity['sha256'],review=p.sha256(review_path),
        bases=[x['output_sha256'] for x in bases],selected=[x['output_sha256'] for x in selected],
        overlap=overlap['output_sha256'],alpha=alpha)
    if incoming_overlap:key_fields['incoming_overlap']=incoming_overlap['output_sha256']
    key=p.json_digest(key_fields)
    name='galaxy_050203_050250' if (start,end)==(50203,50250) else f'neutral_photo_{start:06d}_{end:06d}'
    if incoming_overlap is not None:name=f'dual_neural_{start:06d}_{end:06d}'
    directory=d.BASE/'scientific_joint_trials'/name/('trial_'+key[:16])
    directory.mkdir(parents=True,exist_ok=True);marker=directory/'joint_trial.json'
    if marker.exists():
        old=p.read_json(marker)
        if old.get('status')=='draft_joint_trial_verified_pending_native_review' and all(p.sha256(r['output'])==r['output_sha256'] for r in old['parts']):
            return old,marker
    incoming=support_fields(incoming_overlap['output'],start-incoming_overlap['start_frame'],end-start,pixels,directory/'incoming_support.log') if incoming_overlap else support_fields(identity['path'],start,end-start,pixels,directory/'source_uv_support.log')
    outgoing=support_fields(overlap['output'],start-overlap['start_frame'],end-start,pixels,directory/'outgoing_support.log')
    for src,pred in zip(incoming,outgoing):
        if src[:pixels]!=pred[:pixels]:raise ValueError('Outgoing support mapping differs from exact original source Y')
    uv={f:blend_uv(incoming[f-start],np.frombuffer(outgoing[f-start][pixels:],np.uint8),
        np.frombuffer(incoming[f-start][pixels:],np.uint8),alpha[f],pixels)[pixels:] for f in alpha}
    p.atomic_json(directory/'source_review.snapshot.json',review)
    parts=[]
    for shot,base,prior,parent in zip(shots,bases,selected,parents):
        parent_support=set()
        if parent:
            old=p.read_json(parent['receipt']);parent_support=parent_support_frames(old)
            if old['output_sha256']!=prior['output_sha256'] or old['base_output_sha256']!=base['output_sha256']:
                raise ValueError('Previous disjoint treatment no longer binds its canonical base')
            if parent_support&set(alpha):raise ValueError('Joint patch must not overwrite an existing transition treatment')
        else:old=None
        applied=set(alpha)&set(range(shot['start_frame'],shot['end_frame']))
        allowed=parent_support|applied
        part_dir=directory/shot['id'];part_dir.mkdir(exist_ok=True)
        output=part_dir/'source_y_master.mkv';receipt=part_dir/'treatment.json'
        source=document['source']
        command=[str(p.FFMPEG),'-v','error','-xerror','-y','-f','rawvideo','-pix_fmt','yuv444p','-s',f'{source["width"]}x{source["height"]}',
            '-framerate',f'{source["fps_num"]}/{source["fps_den"]}','-i','pipe:0','-an','-sn','-c:v','ffv1','-level','3','-threads','2',
            '-pix_fmt','yuv444p','-color_range','tv','-colorspace','bt470bg',str(output)]
        with (part_dir/'decode.log').open('w') as log,(part_dir/'encode.log').open('w') as enc_log:
            reader=d.decoder(prior['output'],'yuv444p',log);writer=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=enc_log,stderr=enc_log)
            try:
                for index in range(shot['frames']):
                    frame=d.read_exact(reader.stdout,pixels*3);global_frame=shot['start_frame']+index
                    if len(frame)!=pixels*3:raise ValueError('Short canonical selected input')
                    writer.stdin.write(frame[:pixels]+uv[global_frame] if global_frame in applied else frame)
                    if index%96==0:callback(stage='encoding_joint_trial',shot_id=shot['id'],done=index+1,total=shot['frames'])
                if reader.stdout.read(1):raise ValueError('Excess canonical selected frames')
            finally:
                reader.stdout.close()
                with contextlib.suppress(BrokenPipeError,OSError):writer.stdin.close()
                codes=[reader.wait(),writer.wait()]
            if any(codes):raise ValueError('Joint trial encode failed')
        yhash=hashlib.sha256();outside=hashlib.sha256();all_planes=hashlib.sha256()
        with (part_dir/'verify.log').open('w') as log:
            readers=[d.decoder(item,'yuv444p',log) for item in [base['output'],prior['output'],output]]
            try:
                for index in range(shot['frames']):
                    canonical,before,after=[d.read_exact(child.stdout,pixels*3) for child in readers]
                    global_frame=shot['start_frame']+index
                    if any(len(frame)!=pixels*3 for frame in [canonical,before,after]) or not canonical[:pixels]==before[:pixels]==after[:pixels]:
                        raise ValueError('Joint treatment changed source Y or coverage')
                    expected=before[:pixels]+uv[global_frame] if global_frame in applied else before
                    if after!=expected:raise ValueError('Joint output differs from measured UV or selected prior outside support')
                    if global_frame not in allowed:
                        if canonical[pixels:]!=after[pixels:]:raise ValueError('Joint treatment changed UV outside the declared support union')
                        outside.update(after[pixels:])
                    yhash.update(after[:pixels]);all_planes.update(after)
                if any(child.stdout.read(1) for child in readers):raise ValueError('Excess verified canonical frames')
            finally:
                for child in readers:child.stdout.close()
                codes=[child.wait() for child in readers]
            if any(codes):raise ValueError('Joint output verification decode failed')
        if yhash.hexdigest()!=base['source_y']['sha256']:raise ValueError('Joint output differs from original-Y digest')
        d.verify_video_geometry(output,source);timing=d.verify_timestamps(output,shot['frames'],source)
        record=dict(schema_version=1,status='draft_verified',quality_acceptance='joint_native_review_pending',method=method,
            shot_id=shot['id'],start_frame=shot['start_frame'],end_frame=shot['end_frame'],frames=shot['frames'],
            base_output=base['output'],base_output_sha256=base['output_sha256'],selected_prior_output=prior['output'],selected_prior_sha256=prior['output_sha256'],
            previous_treatment=parent,output=str(output),output_sha256=p.sha256(output),source_sha256=identity['sha256'],
            source_review=str(review_path),source_review_sha256=p.sha256(review_path),joint_fingerprint=key,
            support_frames_global=sorted(applied),verified_support_union_global=sorted(allowed),
            exact_source_y=True,full_decode_verified=True,exact_outside_support_uv=True,exact_previous_treatment_preserved=True,
            source_y=base['source_y'],y_sha256=yhash.hexdigest(),outside_support_uv_sha256=outside.hexdigest(),full_yuv_sha256=all_planes.hexdigest(),timing=timing,
            outgoing_context_output=overlap['output'],outgoing_context_sha256=overlap['output_sha256'],
            limitations=['Alpha is an approximate source-derived trial; both canonical parts require joint visual review.',
                'Previous disjoint entry treatment is retained byte-for-byte; this trial does not accept that earlier treatment.',
                'No delivery registry entry or scope approval is created.'])
        if incoming_overlap:
            record.update(incoming_context_output=incoming_overlap['output'],incoming_context_sha256=incoming_overlap['output_sha256'])
        if old and old.get('outgoing_output_sha256'):
            record.update(outgoing_shot_id=old['outgoing_shot_id'],outgoing_output_sha256=old['outgoing_output_sha256'])
        elif incoming_overlap is None or shot['id']!=shots[0]['id']:
            record.update(outgoing_shot_id=shots[0]['id'],outgoing_output_sha256=bases[0]['output_sha256'])
        p.atomic_json(receipt,record);parts.append(dict(record,receipt=str(receipt),receipt_sha256=p.sha256(receipt)))
    result=dict(schema_version=1,status='draft_joint_trial_verified_pending_native_review',method=method,fingerprint=key,
        source_sha256=identity['sha256'],source_review=str(review_path),source_review_sha256=p.sha256(review_path),
        support_range_half_open=[start,end],canonical_split=shots[1]['start_frame'],source_uv_support_sha256=hashlib.sha256(b''.join(f[pixels:] for f in incoming)).hexdigest(),
        alpha=alpha,parts=parts,exact_source_y=True,exact_outside_support_uv=True,delivery_registry_changed=False,delivery_acceptance=False,finished_at=p.utc())
    p.atomic_json(marker,result)
    return result,marker
