"""Fetch or verify the external pinned model; never vendor it into this repo.

Read THIRD_PARTY.md before using --download. Existing mismatched files are not
overwritten. Downloaded pickle checkpoints must match the recorded SHA256 before
the inference adapter is allowed to deserialize them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def check(path, spec):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size != spec['bytes'] or digest(path) != spec['sha256']:
        raise ValueError(f'Model asset mismatch: {path}; existing file retained')


def download(url, target):
    with urlopen(Request(url, headers={'User-Agent': 'grayscale-video-colorization'}), timeout=90) as source:
        with Path(target).open('wb') as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)


def prepare(repo, allow_download=False):
    spec = json.loads((ROOT / 'model-assets.json').read_text(encoding='utf-8'))
    repo = Path(repo).resolve()
    if not repo.exists():
        if not allow_download:
            raise FileNotFoundError(f'{repo}: run with --download after reviewing dependency terms')
        repo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', '--no-checkout', spec['repository'], str(repo)], check=True)
        subprocess.run(['git', '-C', str(repo), 'checkout', '--detach', spec['commit']], check=True)
    commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != spec['commit']:
        raise ValueError('External CMNET2 commit differs from the tested pin; checkout left unchanged')
    changed = subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain', '--untracked-files=no'], text=True)
    if changed.strip():
        raise ValueError('External CMNET2 tracked code has modifications; review and pin them explicitly')
    with tempfile.TemporaryDirectory(prefix='model-fetch-', dir=repo.parent) as temporary:
        downloads = {}
        for item in spec['files']:
            target = repo / item['path']
            if target.exists():
                check(target, item)
                continue
            if not allow_download:
                raise FileNotFoundError(target)
            url = item['url']
            if url not in downloads:
                archive = Path(temporary) / str(len(downloads))
                download(url, archive)
                downloads[url] = archive
            candidate = downloads[url]
            if 'archive_member_basename' in item:
                extracted = Path(temporary) / ('extracted-' + target.name)
                with zipfile.ZipFile(candidate) as archive:
                    matches = [entry for entry in archive.infolist()
                               if not entry.is_dir() and Path(entry.filename).name == item['archive_member_basename']]
                    if len(matches) != 1 or matches[0].file_size != item['bytes']:
                        raise ValueError('Backbone ZIP lacks one exact expected member')
                    # Do not extract archive paths; copy only this named payload.
                    with archive.open(matches[0]) as source, extracted.open('wb') as output:
                        shutil.copyfileobj(source, output)
                candidate = extracted
            check(candidate, item)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive create avoids clobbering a file installed by another process.
            with candidate.open('rb') as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
            check(target, item)
    return {'status': 'verified', 'commit': commit, 'asset_count': len(spec['files'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT / 'external/cmnet2')
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.repo, args.download), indent=2))
