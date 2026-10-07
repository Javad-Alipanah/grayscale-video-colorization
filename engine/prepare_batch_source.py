"""Prepare a native CPU source cache independently of the single GPU queue."""
import argparse
import os
from pathlib import Path
import production as p

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--manifest', type=Path, required=True)
parser.add_argument('--batch', required=True)
args = parser.parse_args()
document = p.validate_manifest(p.read_json(args.manifest))
status_path = p.HERE/f'{args.batch}_preparation.json'
state = {'status': 'preparing_native_source', 'batch_id': args.batch, 'pid': os.getpid(), 'started_at': p.utc(),
    'manifest': str(args.manifest.resolve()), 'gpu_used': False}
p.atomic_json(status_path, state)
try:
    identity = p.source_identity(document['source'])
    cache = p.prepare_batch(document, args.batch, identity)
    state.update(status='native_source_verified', completed_at=p.utc(), cache=cache)
except BaseException as error:
    state.update(status='failed', error=str(error), completed_at=p.utc())
    raise
finally:
    p.atomic_json(status_path, state)
