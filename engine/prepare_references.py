"""Prepare source-luminance color guides and publish complete per-shot approvals."""
import hashlib
import io
import json
import argparse
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from PIL import Image

from config import PROJECT
BASE = PROJECT
MANIFEST = BASE / 'scenes/manifest.json'

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def atomic_bytes(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.read_bytes() == payload:
            return
    except (FileNotFoundError, PermissionError):
        pass
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with tmp.open('wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                raise  # Preserve the old readable file and complete temporary bytes.
            time.sleep(min(.025 * (2 ** attempt), .25))

def atomic(path, obj):
    atomic_bytes(path, json.dumps(obj, indent=2).encode('utf-8'))

def atomic_png(path, image):
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    payload = buffer.getvalue()
    atomic_bytes(path, payload)
    return hashlib.sha256(payload).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    parser.add_argument('--batch')
    parser.add_argument('--review-file', type=Path, help='Explicit native recombined-guide review, bound to every resulting PNG hash')
    args = parser.parse_args()
    manifest = read(args.manifest)
    review = read(args.review_file) if args.review_file else {}
    if review and (review.get('status') != 'approved' or not review.get('approved_by') or not review.get('approved_at')):
        raise ValueError('An attributed approved guide review is required')
    decisions_path = BASE/'reference_decisions.json'
    omissions = read(decisions_path).get('candidate_omissions', {}) if decisions_path.exists() else {}
    jobs = {}
    for path in sorted((BASE/'reference-jobs').rglob('*.json')):
        j = read(path)
        if j.get('approved') and j.get('generated_path'):
            n = int(j['frame_global'])
            if n in jobs:
                raise ValueError(f'Duplicate approved job for global frame {n}')
            jobs[n] = (j, path)
    records = []
    for shot in manifest['shots']:
        if args.batch and shot['batch_id'] != args.batch:
            continue
        if shot['mode'] != 'colorize':
            continue
        approved = []
        missing = []
        for candidate in shot['reference_candidates']:
            n = candidate['frame_global']
            if str(n) in omissions:
                assert omissions[str(n)]['shot_id'] == shot['id']
                continue
            if n not in jobs:
                missing.append(n)
                continue
            job, job_path = jobs[n]
            source_path = Path(candidate['source_path'])
            assert source_path.resolve() == Path(job['source_path']).resolve()
            assert digest(source_path) == candidate['sha256']
            source = np.asarray(Image.open(source_path).convert('RGB'), dtype=np.float32)
            generated = Image.open(job['generated_path']).convert('RGB')
            guide = np.asarray(generated.resize((source.shape[1], source.shape[0]), Image.Resampling.LANCZOS), dtype=np.float32)
            y = source @ np.array([.299,.587,.114], dtype=np.float32)
            cb = guide @ np.array([-.168736,-.331264,.5], dtype=np.float32)
            cr = guide @ np.array([.5,-.418688,-.081312], dtype=np.float32)
            rgb = np.stack([y+1.402*cr, y-.344136*cb-.714136*cr, y+1.772*cb], axis=-1)
            dest = BASE/'references'/shot['id']/f"ref_{n-shot['start_frame']:06d}.png"
            dest.parent.mkdir(parents=True, exist_ok=True)
            guide_sha256 = atomic_png(dest, Image.fromarray(np.clip(np.rint(rgb),0,255).astype(np.uint8)))
            entry = dict(path=str(dest.resolve()),sha256=guide_sha256,source_frame=n,
                         source_path=str(source_path),source_sha256=candidate['sha256'],
                         view=job.get('view','approved scene view'),materials=job.get('materials',['scene-compatible approved colors']),
                         job_path=str(job_path.resolve()),generated_sha256=digest(job['generated_path']))
            approved.append(entry)
            records.append(dict(shot_id=shot['id'],**entry))
        marker = Path(shot['references_ready'])
        if not missing and approved:
            existing = read(marker) if marker.exists() else {}
            unchanged = existing.get('status') == 'approved' and existing.get('references') == approved
            if unchanged:
                print(json.dumps(dict(shot=shot['id'],approved=len(approved),missing=[],ready=True,unchanged=True)),flush=True)
                continue
            reviewed = review.get('references', [])
            passed = bool(review) and review.get('shot_id') == shot['id'] and all(any(row.get('sha256') == item['sha256']
                and Path(row.get('path','')).resolve() == Path(item['path']).resolve() for row in reviewed) for item in approved)
            proof = dict(schema_version=1,shot_id=shot['id'],status='approved' if passed else 'pending',references=approved,
                   source_sha256=manifest['source'].get('sha256'),
                   approved_by=review.get('approved_by') if passed else None,approved_at=review.get('approved_at') if passed else None,
                   review_path=str(args.review_file.resolve()) if passed else None,
                   review_sha256=digest(args.review_file) if passed else None,
                   method='Source RGB luminance plus generated chroma guides; native recombined guides require explicit review. Final master separately copies exact source Y.')
            if passed:
                from reference_provenance import validate_marker
                from config import WORKSPACE
                validate_marker(shot,manifest['source'],proof,WORKSPACE)
            atomic(marker, proof)
        elif marker.exists():
            # Never leave an old approval active after the planned guide set changes.
            atomic(marker,dict(schema_version=1,shot_id=shot['id'],status='pending',missing=missing))
        print(json.dumps(dict(shot=shot['id'],approved=len(approved),missing=missing,ready=not missing)),flush=True)
    output_name = f'reference_manifest_{args.batch}.json' if args.batch else 'reference_manifest.json'
    atomic(BASE/output_name,records)

if __name__ == '__main__':
    main()
