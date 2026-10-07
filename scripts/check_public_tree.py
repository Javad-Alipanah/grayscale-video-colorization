"""Check the Git index for accidental media, credentials and local paths."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_IMAGES = {f'examples/synthetic/{name}' for name in (
    '01-grayscale.png', '02-chroma-illustration.png', '03-neutral-protection.png')}
FORBIDDEN = {'.mkv','.mp4','.mov','.avi','.webm','.wav','.mp3','.aac','.flac',
             '.raw','.gray','.yuv','.rgb','.pth','.pt','.safetensors','.zip','.7z',
             '.exe','.dll','.pem','.key','.pyc'}
IMAGE = {'.png','.jpg','.jpeg','.gif','.webp'}
SECRET = re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)')
LOCAL = re.compile(rb'(?:[A-Z]:[\\/]+Users[\\/]+[A-Za-z0-9_.-]+|/home/[A-Za-z0-9_.-]+/)', re.I)


def main():
    names = subprocess.check_output(['git','ls-files','-z'], cwd=ROOT).decode().split('\0')
    failures, count, total = [], 0, 0
    for name in filter(None, names):
        path = Path(name)
        if path.suffix.lower() in FORBIDDEN or (path.suffix.lower() in IMAGE and name not in ALLOWED_IMAGES):
            failures.append(f'Excluded binary/media type: {name}')
        if any(part in {'work','data','outputs','external','.venv','weights','models'} for part in path.parts):
            failures.append(f'Private/runtime directory: {name}')
        payload = subprocess.check_output(['git','show', ':'+name], cwd=ROOT)
        count += 1
        total += len(payload)
        if len(payload) > 2*1024*1024:
            failures.append(f'Unexpected >2 MiB file: {name}')
        if path.suffix.lower() not in IMAGE:
            if SECRET.search(payload):
                failures.append(f'Credential-shaped content: {name}')
            if LOCAL.search(payload):
                failures.append(f'Personal absolute path: {name}')
    if not count:
        raise SystemExit('Nothing tracked/staged; run git add on reviewed source first')
    if failures:
        raise SystemExit('\n'.join(failures))
    print(f'Public tree passed: {count} indexed files, {total:,} bytes, only three allowlisted synthetic images permitted.')


if __name__ == '__main__':
    main()
