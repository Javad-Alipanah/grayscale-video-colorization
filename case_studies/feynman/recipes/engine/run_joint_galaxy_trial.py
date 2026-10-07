"""Prepare a two-part scientific dissolve trial, then await bound native QA."""
import argparse
import os
from pathlib import Path
import shutil
import time
import production as p
import delivery as d
import scientific_mask as sm
import paired_neutral_entry as joint

STATUS=p.HERE/'joint_galaxy_trial_status.json'
REVIEW=p.PROJECT/'scenes/qc/dissolves/batch_04/galaxy_onset_refinement/joint_color_review.json'
CONFIG=None


def status(stage,**data):
    p.atomic_json(STATUS,dict(stage=stage,pid=os.getpid(),updated_at=p.utc(),delivery_acceptance=False,**data))


def main():
    if CONFIG is None:
        plan=p.read_json(p.HERE/'science_post_primary/plan.json')
        job=next(j for j in plan['jobs'] if j['boundary_frame']==50225)
        names=['shot_049133','shot_050225'];prior_boundary=49133;nominal_boundary=50225
    else:
        plan=p.read_json(CONFIG)
        if not plan.get('launch_authorized'):raise ValueError('Joint source trial lacks authorization')
        job=plan['job'];names=plan['shot_ids'];prior_boundary=plan['required_prior_entry_boundary'];nominal_boundary=plan['nominal_boundary']
    if job.get('compositor_kind')!='multi_partition_neutral_photo_entry_trial':raise ValueError('Joint neutral-photo trial is not mapped')
    if p.sha256(plan['canonical_manifest'])!=plan['canonical_manifest_sha256']:raise ValueError('Frozen canonical mapping changed')
    if p.sha256(job['source_onset_review'])!=job['source_onset_review_sha256']:raise ValueError('Frozen source onset review changed')
    document=p.validate_manifest(p.read_json(plan['canonical_manifest']));context=p.validate_manifest(p.read_json(job['manifest']))
    if p.sha256(job['manifest'])!=job['manifest_sha256']:raise ValueError('Frozen outgoing context changed')
    identity=p.source_identity(document['source']);runtime=p.runtime_identity()
    shots=[next(s for s in document['shots'] if s['id']==name) for name in names]
    hypothesis=next(s for s in context['shots'] if s['id']==job['id'])
    while True:
        if p.STOP.exists():status('stopped_at_readiness_boundary');return
        try:
            config=sm.load(hypothesis,context['source'],identity)
            attempt=d.choose_attempt(hypothesis,identity,runtime)
            registry=p.read_json(p.HERE/'source_y_overrides.json')
            entry=registry.get(names[0])
            if attempt is None or not entry:
                status('waiting_for_protected_context_and_entry_treatment',context_ready=attempt is not None,entry_treatment_ready=bool(entry));time.sleep(15);continue
            prior=p.read_json(entry['receipt'])
            if prior.get('transition',{}).get('boundary_frame')!=prior_boundary:
                raise ValueError(f'Expected the separately mapped {prior_boundary} entry treatment before the tail trial')
            with p.ExclusiveLock(p.HERE/'boundary_chroma.lock',wait=True),p.ExclusiveLock(p.HERE/'delivery_queue.lock',wait=True):
                bases=[]
                for shot in shots:
                    item=d.choose_attempt(shot,identity,runtime)
                    if item is None:raise ValueError('Canonical trial baseline is unavailable')
                    bases.append(d.merge_one(document,shot,item,identity,lambda **v:status('preparing_joint_bases',**v)))
                previous_id=prior['outgoing_shot_id'];previous_shot=next(s for s in document['shots'] if s['id']==previous_id)
                previous_attempt=d.choose_attempt(previous_shot,identity,runtime)
                previous_base=d.merge_one(document,previous_shot,previous_attempt,identity,lambda **v:status('checking_entry_dependency',**v))
                selected_first=d.apply_source_y_override(bases[0],registry,{previous_id:previous_base})
                minimum=10+1.3*sum(Path(x['output']).stat().st_size for x in bases)/2**30
                if shutil.disk_usage(p.WORKSPACE).free/2**30<minimum:
                    raise sm.ScientificMaskPending('Joint draft storage reserve is not available')
                overlap=d.merge_one(context,hypothesis,attempt,identity,lambda **v:status('preparing_protected_outgoing',**v))
                result,receipt=joint.build(document,shots,bases,[selected_first,bases[1]],[entry,None],overlap,identity,
                    Path(job['source_onset_review']),lambda **v:status(v.pop('stage'),**v))
            break
        except sm.ScientificMaskPending as error:
            status('waiting_for_native_mask_handle',reason=str(error));time.sleep(15)
    receipt_sha=p.sha256(receipt);expected={part['shot_id']:part['output_sha256'] for part in result['parts']}
    while True:
        if p.STOP.exists():status('stopped_at_joint_review_boundary',receipt=str(receipt));return
        if REVIEW.exists():
            review=p.read_json(REVIEW)
            if review.get('status')=='local_joint_transition_pass' and review.get('joint_trial_sha256')==receipt_sha and review.get('output_sha256')==expected:
                if review.get('exact_source_y') is not True or review.get('exact_outside_support_uv') is not True:
                    raise ValueError('Joint local review lacks preservation checks')
                break
        status('joint_trial_ready_pending_native_review',receipt=str(receipt),receipt_sha256=receipt_sha,outputs=expected,review_marker=str(REVIEW));time.sleep(15)
    with p.ExclusiveLock(p.HERE/'boundary_chroma.lock',wait=True):
        registry_path=p.HERE/'source_y_overrides.json';registry=p.read_json(registry_path)
        if registry.get(names[0])!=entry or registry.get(names[1]):
            raise ValueError('A canonical selection changed during joint review; revalidate the pair')
        for part in result['parts']:
            if p.sha256(part['output'])!=part['output_sha256'] or p.sha256(part['receipt'])!=part['receipt_sha256']:
                raise ValueError('Reviewed joint payload changed')
            registry[part['shot_id']]=dict(receipt=part['receipt'],output_sha256=part['output_sha256'],base_output_sha256=part['base_output_sha256'],
                status='active_pending_quality_review',joint_trial_receipt=str(receipt),joint_native_review=str(REVIEW),joint_native_review_sha256=p.sha256(REVIEW),
                support_start_frame=min(part['verified_support_union_global']),support_end_frame_exclusive=max(part['verified_support_union_global'])+1)
        p.atomic_json(registry_path,registry)
        holds_path=p.HERE/'scientific_transition_holds.json';holds=p.read_json(holds_path)
        holds[str(nominal_boundary)].update(status='joint_local_trial_pass_pending_batch_review',joint_receipt=str(receipt),joint_review=str(REVIEW),joint_review_sha256=p.sha256(REVIEW))
        p.atomic_json(holds_path,holds)
    status('joint_trial_selected_pending_batch_review',receipt=str(receipt),receipt_sha256=receipt_sha,outputs=expected,review=str(REVIEW))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config')
    args=parser.parse_args()
    if args.config:
        CONFIG=p.resolve(args.config);config=p.read_json(CONFIG)
        STATUS=p.resolve(config['status_path']);REVIEW=p.resolve(config['review_marker'])
    try:main()
    except BaseException as error:status('failed',error=str(error));raise
