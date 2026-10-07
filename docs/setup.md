# Setup

The production environment was Windows, Python 3.12, an NVIDIA RTX 5070 Laptop
GPU, PyTorch 2.11.0/CUDA 12.8 and transformers 4.57.6. `requirements-tested.txt`
records the actual environment. CPU orchestration/tests can run without the
neural weights. Other platforms and source formats require their own validation.

## Install the runtime

Install Python 3.12, Git, FFmpeg and ffprobe. Keep FFmpeg and ffprobe on PATH,
or set `COLOR_FFMPEG` and `COLOR_FFPROBE` to their absolute executable paths.
Use a new virtual environment; do not change another project's environment.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r requirements.txt
```

On a POSIX shell, activate with `source .venv/bin/activate`. Select an appropriate
PyTorch build for other GPUs, then record the change and rerun the pilot checks;
the above combination is the measured profile, not a universal GPU prescription.

## Model code and weights

Read [THIRD_PARTY.md](../THIRD_PARTY.md) and the upstream terms. The dependency
setup script uses an external checkout, the tested commit and hashes in
`model-assets.json`. It does not accept legal terms on the operator's behalf.

```powershell
python scripts/bootstrap_models.py --download
python scripts/bootstrap_models.py
```

The first command clones the pinned CMNET2 revision and downloads the three
checkpoint files plus the DINOv3 backbone. The second only verifies installed
code/weights. Existing files with wrong hashes or a different tracked checkout
are rejected and left intact. Do not blindly replace them with another version.

An already prepared installation can be used without another download:

```powershell
$env:COLOR_CMNET2 = 'D:/Models/cmnet2'
python scripts/bootstrap_models.py --repo $env:COLOR_CMNET2
```

The model runs offline after installation. The runner uses a small PyTorch
correlation adapter in `inference/`; this avoids compiling the unsupported CUDA
extension on the tested Windows setup. Verify it on your CPU and GPU:

```powershell
python inference/check_correlation.py
```

Its test needs a CUDA GPU. This is a mathematical-operation comparison, not
proof of bit-identical behavior across every CUDA/cuDNN version.

## State and configuration

| Variable | Purpose |
| --- | --- |
| `COLOR_WORKSPACE` | Root for relative artifact paths |
| `COLOR_PROJECT` | A single video's persistent project directory |
| `COLOR_PYTHON` | Interpreter used by inference subprocesses |
| `COLOR_CMNET2` | External pinned CMNET2 checkout |
| `COLOR_FFMPEG`, `COLOR_FFPROBE` | Executables, optionally absolute paths |

Use separate project directories for separate lectures. The CLI sets project
context for its child process; do not run the historical Lecture 1 recipe scripts
against a new lecture without inspecting their assumptions. The active production
job used during repository extraction was not moved into this repository.

Historical Lecture 1 entrypoints retained in `engine/` additionally require
`COLOR_ENABLE_LECTURE1_RECIPES=1` and `COLOR_LECTURE1_SOURCE` pointing to the exact
recorded source hash. This guard does not adapt their private paths or approvals.
Use `pipeline.py` for later lectures. The separate case-study recipe archive has
its own [limitations](../case_studies/feynman/README.md); do not import it as a
library.

Begin with the commands in the README. The operator supplies a source video they
are entitled to process, a reviewed shot census, and reviewed reference images.
The package does not automatically log into sites, download protected films,
generate guides using a paid service, or approve results.

## Optional segmentation assets

The historical moving-foreground recipes used
`facebook/sam2.1-hiera-tiny` revision
`de431c4043854a71d8101e17995dfe596bf101a5`, through transformers 4.57.6.
`sam2-assets.json` records the four installed file hashes, and the
[official model card](https://huggingface.co/facebook/sam2.1-hiera-tiny) identifies
Apache-2.0 terms. The recipes still require source-aligned geometry/anchor plans
and adaptation of their private case-study paths.

```powershell
python scripts/bootstrap_sam2.py --download
python scripts/bootstrap_sam2.py
```

This optional installer does not run segmentation or approve masks. Manual
reviewed mattes can be used without these assets. Do not run an independent
GPU segmentation job concurrently with the colorization queue; route it through
the same GPU lock and bounded source-frame plan.
