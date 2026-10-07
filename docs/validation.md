# Validation record

Recorded 7 October 2026. Technical preservation, visual approval and software
portability are separate claims.

## Original Lecture 1 production

The original production used the profile in
[`source-inventory.json`](../case_studies/feynman/source-inventory.json), with
CMNET2 DINOv3, float32 inference, maximum model side 512, and fresh inference
processes at reviewed camera cuts. Native output is 960×720 at 24000/1001 fps.
Its 80,026 source frames form 102 contiguous intervals across six batches.

Independent checks of the assembled FFV1/PCM lossless master passed:

- All 80,026 original decoded Y planes preserved exactly.
- All 1,281,687,552 decoded original PCM bytes retained through natural EOF,
  including the audio tail; 160,210,944 samples per channel.
- Every decoded video presentation timestamp retained, with a maximum measured
  floating-point difference of 4.55e-13 seconds; decoded audio-frame timestamps
  and sample counts also matched.
- The accepted 4,320-frame pilot range retained exact native Y, U and V planes.

Scoped review covered references, protected scientific material, localized
corrections and transitions. The owner elected to perform the full 55:38
continuous viewing review. These technical proofs do not claim that this human
review has happened or that every interpretive color is historically authentic.
The copyrighted source, complete media and private evidence tree are not public.

## Portable repository

The repository extracts and adapts that production code. It does not claim a
second full-lecture GPU rerender from a clean installation. Model and optional
SAM 2 asset hashes were checked against the installed assets. CPU tests run in
a separate Python 3.12 environment installed from `requirements-cpu.txt`.

The suite covers real FFmpeg preservation cases as well as queue/review/resume
state transitions: changed source luminance, lost audio tails, AAC priming,
matrix retagging, timestamp shifts, immutable reuse, stale reference reviews,
rejected outputs, reference scope, protected masks and queue dependencies.
GitHub Actions runs the CPU suite on Ubuntu; the original production ran on
Windows. Consult the workflow result for the current commit.

The extracted repository passed 87 tests in a clean CPU environment. A real
24-frame synthetic exercise also ran `init`, `next`, `status`, `render`,
`deliver`, explicit fixture `review`, and `assemble`, then independently verified
source Y, original decoded audio through EOF and native timestamps. This uses
passthrough shots, so it tests orchestration and preservation without claiming
neural color quality. It keeps final visual acceptance pending. Its replayable
script is included and runs in CI.

Run locally, with FFmpeg and ffprobe on PATH (or their documented environment
overrides):

```powershell
python -m pip install -r requirements-cpu.txt
$env:PYTHONPATH = (Resolve-Path engine).Path
python -m unittest discover -s tests -v
python scripts/smoke_passthrough.py
python scripts/check_public_tree.py
```

The content check reads the Git index, so stage intended changes before running
it. It rejects media/model binaries, private runtime state, oversized files,
personal absolute paths and credential-shaped content. It is a publication aid,
not a guarantee that arbitrary future additions are safe to publish.

## Independent whole-master check

After assembly, use the source and the **lossless master**, not the viewing MP4:

```powershell
python scripts/verify_preservation.py --source D:/Media/source.mkv --master D:/PrivateRun/master.mkv --report D:/PrivateRun/preservation.json
```

The default video timestamp comparison is exact. Only where reviewed container
rounding requires it, explicitly allow at most 1 ms with `--pts-tolerance-ms`;
the receipt records the allowance and actual error rather than claiming exact
equality. Optional `--immutable` and `--immutable-start` check a reused native
YUV range. The verifier never marks visual acceptance or continuous playback as
complete. Lossy viewing files require their own EOF/decode and playback checks.
