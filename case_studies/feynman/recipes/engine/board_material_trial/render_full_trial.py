"""Unselected full-shot board material trial from reviewed source geometry."""
import argparse
import contextlib
import copy
import hashlib
from pathlib import Path
import shutil
import sys
import numpy as np
import cv2
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
import production as p
import delivery as d
from render_crest_trial import encode
cv2.setNumThreads(2)
P = 960*720
STATUS = ROOT/'full_trial_status.json'


def status(stage, **kw):
    p.atomic_json(STATUS, dict(stage=stage, updated_at=p.utc(), selection_changed=False,
                              delivery_acceptance=False, **kw))


def smooth(values):
    values = np.clip(values, 0, 1)
    return values*values*(3-2*values)


def alpha_for_frame(before, geometry, foreground):
    panel = Image.new('L', (960,720)); draw = ImageDraw.Draw(panel)
    draw.polygon([tuple(v) for v in geometry['screen_polygon_native']], fill=255)
    for obj in geometry['source_object_exclusions']:
        draw.polygon([tuple(v) for v in obj['polygon_native']], fill=0)
    actor = np.array(Image.open(foreground['mask_path']).convert('L'))
    if actor.shape != (720,960) or not np.isin(actor, [0,255]).all():
        raise ValueError('Foreground is not native binary geometry')
    core = actor > 0
    guard = cv2.dilate(core.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17,17))) > 0
    region = np.array(panel) > 0; region[guard] = False
    feather = smooth((cv2.distanceTransform(region.astype(np.uint8), cv2.DIST_L2, 5)-.5)/6)
    # This smaller margin is opt-in source evidence for each frame. Never erode
    # the actual actor or transfer the two-pose experiment to all motion.
    rows = foreground.get('clear_right_back_rows')
    if rows is not None:
        if not foreground.get('clear_right_back_native_review'):
            raise ValueError('Narrow back guard lacks explicit source review')
        lo, hi = rows
        if not (0 <= lo < hi <= 720): raise ValueError('Invalid clear-back rows')
        narrow = cv2.dilate(core.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))) > 0
        narrow_region = np.array(panel) > 0; narrow_region[narrow] = False
        local = smooth((cv2.distanceTransform(narrow_region.astype(np.uint8), cv2.DIST_L2, 5)-.5)/3)
        weight = np.zeros((720,960), np.float32)
        for y in range(lo,hi):
            xs = np.flatnonzero(core[y])
            if len(xs):
                edge = xs[-1]
                weight[y,edge+1:min(960,edge+28)] = smooth(min((y-lo)/12,(hi-1-y)/12))
        feather = feather*(1-weight)+local*weight
    uv = before[1:].astype(np.float32)
    warm = smooth((uv[1]-125.5)/5)
    chroma = smooth((np.sqrt(((uv-128)**2).sum(axis=0))-3)/3)
    chalk = 1-smooth((before[0].astype(np.float32)-170)/40)
    alpha = np.rint(feather*warm*chroma*chalk*255).astype(np.uint8)
    if np.any(alpha[core]): raise ValueError('Alpha changes source actor core')
    return alpha


def main(map_path):
    foreground = p.read_json(map_path)
    if foreground.get('native_visual_review_pass') is not True or foreground.get('unresolved_frames'):
        raise ValueError('A closed native source-foreground review is required for the trial')
    review_path = Path(foreground['review_receipt'])
    if p.sha256(review_path) != foreground['review_receipt_sha256']:
        raise ValueError('Source-foreground review changed')
    mapping = {int(row['frame_global']):row for row in foreground['frames']}
    expected = set(range(76493,76670)) | set(range(77070,77633))
    if len(foreground['frames']) != 740 or set(mapping) != expected:
        raise ValueError('Foreground global coverage differs from reviewed bounded plan')
    for row in mapping.values():
        row['mask_path'] = str(p.resolve(row['mask_path']))
        if p.sha256(row['mask_path']) != row['mask_sha256']:
            raise ValueError('Reviewed foreground payload changed')
    panel_path = p.PROJECT/'reference-jobs/worker/batch06_output_review/board_mapping/physical_plane_v06/geometry_proposal.json'
    if p.sha256(panel_path) != 'b19c4930cbf878a43521c05b8959a718b38f2df1a55a21d00538a659da603001':
        raise ValueError('Reviewed physical panel changed')
    panels = {r['frame_global']:r for r in p.read_json(panel_path)['frames']}
    prior_choice = p.read_json(p.HERE/'source_y_overrides.json')['shot_074465']
    prior_path = Path(prior_choice['receipt']); prior = p.read_json(prior_path)
    if prior['output_sha256'] != 'fb0c1283b0784ad153520e12b98232671dc4febf483fefa31cd80c988a7ff02f':
        raise ValueError('Selected reviewed closing onset changed')
    if p.sha256(prior['output']) != prior['output_sha256']:
        raise ValueError('Native baseline changed')
    if prior['start_frame'] != 74465 or prior['end_frame'] != 77632:
        raise ValueError('Canonical shot coverage changed')
    target_path = ROOT/'anchor_color_v01/trial.json'; target_review = p.read_json(target_path)
    if target_review['native_target_uv'] != [125.,124.]: raise ValueError('Approved existing palette measurement changed')
    fingerprint = p.json_digest(dict(prior=p.sha256(prior_path), foreground=p.sha256(map_path),
        foreground_review=p.sha256(review_path), panel=p.sha256(panel_path),
        target=p.sha256(target_path), implementation=p.sha256(__file__)))
    out = d.BASE/'material_trials/shot_074465'/('board_'+fingerprint[:16]); out.mkdir(parents=True,exist_ok=True)
    receipt = out/'treatment.json'; output = out/'source_y_master.mkv'; alpha_path = out/'material_alpha_ffv1.mkv'
    if receipt.exists():
        ready = p.read_json(receipt)
        if ready.get('full_decode_verified') and p.sha256(output) == ready['output_sha256']:
            status('full_board_candidate_ready_pending_native_QA', receipt=str(receipt)); return
    if shutil.disk_usage(p.WORKSPACE).free/2**30 < 10+1.3*(Path(prior['output']).stat().st_size/2**30+.1):
        raise ValueError('Insufficient storage preserving 30% allowance and10GiB reserve')
    source = p.read_json(p.HERE/'batch_06_manifest.json')['source']
    yhash=hashlib.sha256(); payload=hashlib.sha256(); ahash=hashlib.sha256(); unchanged=hashlib.sha256(); outside_union=hashlib.sha256()
    target=np.array([125.,124.], np.float32)[:,None,None]
    modified=[]; measurements=[]
    with p.ExclusiveLock(p.HERE/'boundary_chroma.lock',wait=True), p.ExclusiveLock(p.HERE/'delivery_queue.lock',wait=True):
        if p.read_json(p.HERE/'source_y_overrides.json')['shot_074465'] != prior_choice:
            raise ValueError('Selected baseline changed while waiting for CPU lock')
        with (out/'media.log').open('w') as log:
            decoder=d.decoder(prior['output'],'yuv444p',log)
            writer=encode(output,source,'yuv444p',log); awriter=encode(alpha_path,source,'gray',log)
            try:
                for local in range(prior['frames']):
                    frame=prior['start_frame']+local; raw=d.read_exact(decoder.stdout,P*3)
                    if len(raw)!=P*3: raise ValueError('Short baseline decode')
                    before=np.frombuffer(raw,np.uint8).reshape(3,720,960)
                    alpha=alpha_for_frame(before,panels[frame],mapping[frame]) if frame in mapping else np.zeros((720,960),np.uint8)
                    after=before.copy(); weight=alpha.astype(np.float32)/255
                    after[1:]=np.rint(before[1:].astype(np.float32)*(1-weight)+target*weight).clip(0,255).astype(np.uint8)
                    if not np.array_equal(after[0],before[0]) or not np.array_equal(after[1:,alpha==0],before[1:,alpha==0]):
                        raise ValueError('SourceY/outside-alpha invariant failed')
                    changed=int(np.count_nonzero(np.any(after[1:]!=before[1:],axis=0)))
                    if changed:modified.append(frame)
                    else:
                        unchanged.update(after.tobytes())
                        if not prior['transition']['support_start_frame']<=frame<prior['transition']['support_end_frame_exclusive']:
                            outside_union.update(after[1:].tobytes())
                    if frame in mapping:measurements.append(dict(frame_global=frame,changed_pixels=changed,alpha_pixels=int(np.count_nonzero(alpha)),mean_abs_uv_change=float(np.abs(after[1:].astype(float)-before[1:]).mean())))
                    data=after.tobytes(); abytes=alpha.tobytes()
                    payload.update(data); yhash.update(data[:P]); ahash.update(abytes)
                    writer.stdin.write(data); awriter.stdin.write(abytes)
                    if local%64==0:status('rendering_full_source_Y_board_trial',done=local+1,total=prior['frames'])
                if decoder.stdout.read(1):raise ValueError('Excess baseline frames')
            finally:
                decoder.stdout.close()
                for child in [writer,awriter]:
                    with contextlib.suppress(OSError):child.stdin.close()
                codes=[child.wait() for child in [decoder,writer,awriter]]
            if any(codes):raise ValueError('Board trial media process failed')
        if yhash.hexdigest()!=prior['y_sha256']:raise ValueError('Original full-shot Y hash changed')
        status('verifying_full_board_trial_decode')
        verified=hashlib.sha256(); verified_alpha=hashlib.sha256()
        with (out/'verify.log').open('w') as log:
            decoded=d.decoder(output,'yuv444p',log); adecoded=d.decoder(alpha_path,'gray',log)
            try:
                for _ in range(prior['frames']):
                    raw=d.read_exact(decoded.stdout,P*3); a=d.read_exact(adecoded.stdout,P)
                    if len(raw)!=P*3 or len(a)!=P:raise ValueError('Short trial/alpha verification')
                    verified.update(raw); verified_alpha.update(a)
                if decoded.stdout.read(1) or adecoded.stdout.read(1):raise ValueError('Excess verified frames')
            finally:
                decoded.stdout.close();adecoded.stdout.close();codes=[decoded.wait(),adecoded.wait()]
            if any(codes):raise ValueError('Trial/alpha verification decode failed')
        if verified.hexdigest()!=payload.hexdigest() or verified_alpha.hexdigest()!=ahash.hexdigest():
            raise ValueError('Encoded trial/alpha differs from constructed frames')
        timing=d.verify_timestamps(output,prior['frames'],source);d.verify_video_geometry(output,source)
        support=set(modified)|set(range(prior['transition']['support_start_frame'],prior['transition']['support_end_frame_exclusive']))
        record=copy.deepcopy(prior)
        record.update(status='draft_verified',quality_acceptance='native_material_review_pending',fingerprint=fingerprint,
            output=str(output),output_sha256=p.sha256(output),method='Reviewed closing onset plus bounded source-tracked board material UV trial; originalY exact',
            exact_source_y=True,full_decode_verified=True,exact_outside_support_uv=True,exact_uv_outside_material_alpha=True,
            exact_prior_onset_yuv=True,verified_support_union_global=sorted(support),y_sha256=yhash.hexdigest(),full_yuv_sha256=verified.hexdigest(),outside_support_uv_sha256=outside_union.hexdigest(),
            material_changed_frames=modified,material_alpha=str(alpha_path),material_alpha_sha256=p.sha256(alpha_path),material_alpha_decoded_sha256=ahash.hexdigest(),
            material_prior_output=prior['output'],material_prior_output_sha256=prior['output_sha256'],material_prior_receipt=str(prior_path),material_prior_receipt_sha256=p.sha256(prior_path),
            foreground_map=str(map_path),foreground_map_sha256=p.sha256(map_path),physical_panel=str(panel_path),physical_panel_sha256=p.sha256(panel_path),
            source_foreground_review=str(review_path),source_foreground_review_sha256=p.sha256(review_path),native_target_uv=[125,124],
            target_measurement=str(target_path),target_measurement_sha256=p.sha256(target_path),timing=timing,finished_at=p.utc(),
            selection_changed=False,delivery_acceptance=False,limitations=['All affected moving board/actor edges and temporal windows require independent native review before selection.'])
        p.atomic_json(out/'per_frame_measurements.json',measurements);p.atomic_json(receipt,record)
    status('full_board_candidate_ready_pending_native_QA',receipt=str(receipt),output_sha256=record['output_sha256'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--foreground-map',type=Path,required=True);args=parser.parse_args()
    try:main(args.foreground_map)
    except BaseException as error:status('failed',error=str(error));raise
