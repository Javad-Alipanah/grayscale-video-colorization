"""Optional pinned SAM 2 assets for adapting the historical mask recipes."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
from bootstrap_models import ROOT, check, download


def prepare(target, allow_download=False):
    spec = json.loads((ROOT/'sam2-assets.json').read_text(encoding='utf-8'))
    target = Path(target).resolve()
    if not target.exists() and not allow_download:
        raise FileNotFoundError(target)
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sam2-fetch-', dir=target.parent) as temp:
        for item in spec['files']:
            path = target/item['path']
            if path.exists():
                check(path, item)
                continue
            if not allow_download:
                raise FileNotFoundError(path)
            candidate = Path(temp)/item['path']
            download(item['url'], candidate)
            check(candidate, item)
            with candidate.open('rb') as source, path.open('xb') as dest:
                shutil.copyfileobj(source, dest)
            check(path, item)
    return {'status': 'verified', 'revision': spec['revision'], 'files': len(spec['files'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=ROOT/'external/sam2.1-hiera-tiny')
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.target, args.download), indent=2))
