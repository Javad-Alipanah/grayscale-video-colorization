"""Atomically publish a hash-bound, explicitly reviewed native PNG guide set.

This records an operator's existing review; it does not perform visual review.
The JSON protocol is documented in docs/reference-protocol.md.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pipeline


def validate(review, shot, source, base):
    from PIL import Image
    if (review.get('status') != 'approved' or review.get('shot_id') != shot['id']
            or review.get('source_sha256') != source['sha256']
            or not all(review.get(k) for k in ('approved_by', 'approved_at', 'notes'))):
        raise ValueError('Attributed approval for this shot and exact source is required')
    for key in ('geometry_checked', 'palette_checked', 'source_y_recombined_checked'):
        if review.get(key) is not True:
            raise ValueError(f'Explicit visual check required: {key}')
    items = review.get('references', [])
    if not items:
        raise ValueError('At least one reviewed reference is required')
    resolved, seen = [], set()
    for row in items:
        frame = row.get('source_frame')
        if type(frame) is not int or not shot['start_frame'] <= frame < shot['end_frame'] or frame in seen:
            raise ValueError('Duplicate or out-of-shot source frame')
        path = Path(row['path'])
        path = path.resolve() if path.is_absolute() else (base/path).resolve()
        match = re.fullmatch(r'ref_(\d+)\.png', path.name)
        if match is None or int(match[1]) != frame-shot['start_frame']:
            raise ValueError('PNG name must be ref_SHOT_LOCAL_FRAME.png')
        if pipeline.digest(path) != row.get('sha256'):
            raise ValueError('Reviewed PNG checksum changed')
        with Image.open(path) as image:
            image.load()
            if image.format != 'PNG' or image.size != (source['width'], source['height']) or image.mode != 'RGB':
                raise ValueError('Guide must be a native-size RGB PNG')
        if not row.get('view') or not isinstance(row.get('materials'), list) or not row['materials']:
            raise ValueError('Describe the source-compatible view and materials')
        seen.add(frame)
        resolved.append(dict(row, path=str(path)))
    return resolved


def publish(project, review_path):
    project, review_path = Path(project).resolve(), Path(review_path).resolve()
    os.environ['COLOR_PROJECT'] = str(project)
    sys.path.insert(0, str(ROOT/'engine'))
    import production as p
    # Same lock used by all production projects in this workspace.
    with p.ExclusiveLock(p.GPU_LOCK):
        state, manifest = pipeline.load_project(project, check_references=False)
        review = pipeline.read(review_path)
        shot = next((s for s in manifest['shots'] if s['id'] == review.get('shot_id')), None)
        if shot is None or shot['mode'] != 'colorize':
            raise ValueError('Guide publication requires a known colorize shot')
        unresolved = pipeline.next_batch(state)
        if unresolved is None or shot['batch_id'] != unresolved['id']:
            raise ValueError('Publish references for the next unresolved batch only')
        rows = validate(review, shot, manifest['source'], review_path.parent)
        fingerprint = pipeline.digest(review_path)
        folder = project/'references'/shot['id']/('set_'+fingerprint[:16])
        folder.mkdir(parents=True, exist_ok=True)
        # Copy under new versioned names; old approved references remain intact.
        references = []
        for row in rows:
            src = Path(row['path'])
            dst = folder/src.name
            payload = src.read_bytes()
            if hashlib.sha256(payload).hexdigest() != row['sha256']:
                raise ValueError('Guide changed during publication')
            if dst.exists():
                if pipeline.digest(dst) != row['sha256']:
                    raise ValueError('Existing versioned guide differs')
            else:
                with dst.open('xb') as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
            references.append(dict(row, path=str(dst)))
        stored_review = folder/'review.json'
        p.atomic_json(stored_review, review)
        marker = Path(shot['references_ready'])
        marker = marker if marker.is_absolute() else p.WORKSPACE/marker
        if not marker.resolve().is_relative_to(project):
            raise ValueError('Readiness marker must remain inside this project')
        proof = dict(schema_version=1, shot_id=shot['id'], status='approved',
                     source_sha256=manifest['source']['sha256'],
                     approved_by=review['approved_by'], approved_at=review['approved_at'],
                     references=references, review_path=str(stored_review),
                     review_sha256=p.sha256(stored_review),
                     method='Operator-reviewed native guide set; no automatic visual acceptance')
        p.atomic_json(marker, proof)
        p.approved_references(p.validate_manifest(manifest)['shots'][manifest['shots'].index(shot)])
    return {'marker': str(marker), 'references': len(references), 'status': 'approved'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--review-file', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(publish(args.project, args.review_file), indent=2))
