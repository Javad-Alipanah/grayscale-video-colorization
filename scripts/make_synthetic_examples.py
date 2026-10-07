"""Generate three original algorithmic fixtures, not footage or model results."""
from pathlib import Path
import json
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / 'examples/synthetic'
    out.mkdir(parents=True, exist_ok=True)
    h, w = 144, 192
    yy, xx = np.mgrid[:h, :w]
    y = (40 + xx * 130 // w + (yy % 19 < 2) * 20).astype(np.uint8)
    y[25:65, 112:179] = 200
    u = np.full((h, w), 128, dtype=np.uint8)
    v = u.copy()
    u[:, :96] = 155
    v[:, :96] = 118
    u[:, 96:] = 100
    v[:, 96:] = 147
    # A neutral scientific inset remains source chroma.
    u[25:65, 112:179] = 128
    v[25:65, 112:179] = 128
    gray = np.repeat(y[..., None], 3, axis=2)
    c = (y.astype(float) - 16) * 255 / 219
    d = (u.astype(float) - 128) * 255 / 224
    e = (v.astype(float) - 128) * 255 / 224
    rgb = np.clip(np.stack([c + 1.402*e, c - .344136*d - .714136*e, c + 1.772*d], axis=-1), 0, 255).round().astype(np.uint8)
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[25:65, 112:179] = 255
    Image.fromarray(gray).save(out / '01-grayscale.png')
    Image.fromarray(rgb).save(out / '02-chroma-illustration.png')
    Image.fromarray(mask).save(out / '03-neutral-protection.png')
    (out / 'provenance.json').write_text(json.dumps({
        'creator': 'Javad Alipanah project', 'license': 'MIT',
        'kind': 'algorithmic geometric fixtures; no third-party footage',
        'note': 'Illustrates concepts only. Not CMNET2 output or Feynman colorization quality evidence.',
        'generator': 'scripts/make_synthetic_examples.py',
        'native_y_note': 'The internal Y array is shared. Display RGB conversions/clipping are not byte-exact Y proof.'
    }, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
